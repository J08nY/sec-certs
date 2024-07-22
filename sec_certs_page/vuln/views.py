from operator import itemgetter
from pathlib import Path

import sentry_sdk
from flask import abort, current_app, render_template, request, send_file
from flask_breadcrumbs import register_breadcrumb

from .. import mongo, sitemap
from ..common.objformats import load
from . import vuln


@vuln.route("/")
@register_breadcrumb(vuln, ".", "Vulnerability information")
def index():
    return render_template("vuln/index.html.jinja2", title="Vulnerability information | sec-certs.org")


@vuln.route("/cve/cve.json")
def cve_dset():
    dset_path = Path(current_app.instance_path) / current_app.config["DATASET_PATH_CVE"]
    if not dset_path.is_file():
        return abort(404)
    return send_file(
        dset_path,
        as_attachment=True,
        mimetype="application/json",
        download_name="cve.json",
    )


@vuln.route("/cve/cve.json.gz")
def cve_dset_gz():
    dset_path = Path(current_app.instance_path) / current_app.config["DATASET_PATH_CVE_COMPRESSED"]
    if not dset_path.is_file():
        return abort(404)
    return send_file(
        dset_path,
        as_attachment=True,
        mimetype="application/json",
        download_name="cve.json.gz",
    )


@vuln.route("/cve/<string:cve_id>")
@register_breadcrumb(
    vuln,
    ".cve",
    "",
    dynamic_list_constructor=lambda *args, **kwargs: [{"text": request.view_args["cve_id"]}],  # type: ignore
)
def cve(cve_id):
    with sentry_sdk.start_span(op="mongo", description="Find CVE"):
        cve_doc = mongo.db.cve.find_one({"_id": cve_id})
    if not cve_doc:
        return abort(404)
    criteria = set()
    criteria |= set(vuln_cpe["criteria_id"] for vuln_cpe in cve_doc["vulnerable_cpes"])
    for vuln_cfg in cve_doc["vulnerable_criteria_configurations"]:
        for vuln_component in vuln_cfg["components"]:
            criteria |= set(vuln_match["criteria_id"] for vuln_match in vuln_component)

    with sentry_sdk.start_span(op="mongo", description="Find CPE matches"):
        matches = {match["_id"]: match for match in mongo.db.cpe_match.find({"_id": {"$in": list(criteria)}})}

    vuln_configs = []
    for vuln_cpe in cve_doc["vulnerable_cpes"]:
        match = matches.get(vuln_cpe["criteria_id"])
        if match:
            vuln_configs.append((list(map(itemgetter("cpeName"), match["matches"])), []))
    for vuln_cfg in cve_doc["vulnerable_criteria_configurations"]:
        matches_first = []
        for crit in vuln_cfg["components"][0]:
            match = matches.get(crit["criteria_id"])
            if match:
                matches_first.extend(list(map(itemgetter("cpeName"), match["matches"])))
        matches_second = []
        if len(vuln_cfg["components"]) > 1:
            for crit in vuln_cfg["components"][1]:
                match = matches.get(crit["criteria_id"])
                if match:
                    matches_second.extend(list(map(itemgetter("cpeName"), match["matches"])))
        vuln_configs.append((matches_first, matches_second))

    with sentry_sdk.start_span(op="mongo", description="Find CC certs"):
        cc_certs = list(map(load, mongo.db.cc.find({"heuristics.related_cves._value": cve_id})))
    with sentry_sdk.start_span(op="mongo", description="Find FIPS certs"):
        fips_certs = list(map(load, mongo.db.fips.find({"heuristics.related_cves._value": cve_id})))
    return render_template(
        "vuln/cve.html.jinja2", cve=load(cve_doc), cc_certs=cc_certs, fips_certs=fips_certs, vuln_configs=vuln_configs
    )


@vuln.route("/cpe/cpe_match.json")
def cpe_match_dset():
    dset_path = Path(current_app.instance_path) / current_app.config["DATASET_PATH_CPE_MATCH"]
    if not dset_path.is_file():
        return abort(404)
    return send_file(
        dset_path,
        as_attachment=True,
        mimetype="application/json",
        download_name="cpe_match.json",
    )


@vuln.route("/cpe/cpe_match.json.gz")
def cpe_match_dset_gz():
    dset_path = Path(current_app.instance_path) / current_app.config["DATASET_PATH_CPE_MATCH_COMPRESSED"]
    if not dset_path.is_file():
        return abort(404)
    return send_file(
        dset_path,
        as_attachment=True,
        mimetype="application/json",
        download_name="cpe_match.json.gz",
    )


@vuln.route("/cpe/<path:cpe_id>")
@register_breadcrumb(
    vuln,
    ".cpe",
    "",
    dynamic_list_constructor=lambda *args, **kwargs: [{"text": request.view_args["cpe_id"]}],  # type: ignore
)
def cpe(cpe_id):
    with sentry_sdk.start_span(op="mongo", description="Find CPE"):
        cpe_doc = mongo.db.cpe.find_one({"_id": cpe_id})
    if not cpe_doc:
        return abort(404)

    with sentry_sdk.start_span(op="mongo", description="Find CC certs"):
        cc_certs = list(map(load, mongo.db.cc.find({"heuristics.cpe_matches._value": cpe_id})))
    with sentry_sdk.start_span(op="mongo", description="Find FIPS certs"):
        fips_certs = list(map(load, mongo.db.fips.find({"heuristics.cpe_matches._value": cpe_id})))
    with sentry_sdk.start_span(op="mongo", description="Find CVEs"):
        match_ids = list(map(itemgetter("_id"), mongo.db.cpe_match.find({"matches.cpeName": cpe_id}, ["_id"])))
        # XXX: If we want to include the "running on/with" part of the matching then we need one more or
        #      in this statement (for components.1).
        cves = sorted(
            map(
                load,
                mongo.db.cve.find(
                    {
                        "$or": [
                            {"vulnerable_cpes.criteria_id": {"$in": match_ids}},
                            {"vulnerable_criteria_configurations.components.0.criteria_id": {"$in": match_ids}},
                        ]
                    }
                ),
            ),
            key=itemgetter("_id"),
        )
    return render_template(
        "vuln/cpe.html.jinja2", cpe=load(cpe_doc), cc_certs=cc_certs, fips_certs=fips_certs, cves=cves
    )


@vuln.route("/cpe/cpe.json")
def cpe_dset():
    dset_path = Path(current_app.instance_path) / current_app.config["DATASET_PATH_CPE"]
    if not dset_path.is_file():
        return abort(404)
    return send_file(
        dset_path,
        as_attachment=True,
        mimetype="application/json",
        download_name="cpe.json",
    )


@vuln.route("/cpe/cpe.json.gz")
def cpe_dset_gz():
    dset_path = Path(current_app.instance_path) / current_app.config["DATASET_PATH_CPE_COMPRESSED"]
    if not dset_path.is_file():
        return abort(404)
    return send_file(
        dset_path,
        as_attachment=True,
        mimetype="application/json",
        download_name="cpe.json.gz",
    )


@sitemap.register_generator
def sitemap_urls():
    yield "vuln.index", {}
    yield "vuln.cve_dset", {}
    yield "vuln.cve_dset_gz", {}
    yield "vuln.cpe_dset", {}
    yield "vuln.cpe_dset_gz", {}
    yield "vuln.cpe_match_dset", {}
    yield "vuln.cpe_match_dset_gz", {}
    for doc in mongo.db.cve.find({}, {"_id": 1}):
        yield "vuln.cve", {"cve_id": doc["_id"]}
    for doc in mongo.db.cpe.find({}, {"_id": 1}):
        yield "vuln.cpe", {"cpe_id": doc["_id"]}
