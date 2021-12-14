"""FIPS views."""

import random
import re
from operator import itemgetter
from pathlib import Path

import pymongo
import sentry_sdk
from flask import abort, current_app, redirect, render_template, request, url_for, send_file
from flask_breadcrumbs import register_breadcrumb
from networkx import node_link_data

from .. import mongo, cache
from ..utils import Pagination, add_dots, network_graph_func, send_json_attachment
from . import fips, fips_types, get_fips_graphs, get_fips_map


@fips.app_template_global("get_fips_type")
def get_fips_type(name):
    return fips_types.get(name, None)


@fips.route("/types.json")
@cache.cached(60 * 60)
def types():
    return send_json_attachment(fips_types)


@fips.route("/")
@register_breadcrumb(fips, ".", "FIPS 140")
def index():
    return render_template("fips/index.html.jinja2", title="FIPS 140 | seccerts.org")


@fips.route("/dataset.json")
def dataset():
    return send_file(Path(current_app.instance_path) / current_app.config["DATASET_PATH_FIPS_OUT"], as_attachment=True,
                     mimetype="application/json", attachment_filename="dataset.json")


@fips.route("/network/")
@register_breadcrumb(fips, ".network", "References")
def network():
    return render_template(
        "fips/network.html.jinja2",
        url=url_for(".network_graph"),
        title="FIPS 140 network | seccerts.org",
    )


@fips.route("/network/graph.json")
@cache.cached(5 * 60)
def network_graph():
    return network_graph_func(get_fips_graphs())


def select_certs(q, cat, status, sort):
    categories = fips_types.copy()
    query = {}
    projection = {
        "_id": 1,
        "cert_id": 1,
        "web_scan.module_name": 1,
        "web_scan.status": 1,
        "web_scan.level": 1,
        "web_scan.vendor": 1,
        "web_scan.module_type": 1,
        "web_scan.date_validation": 1,
        "web_scan.date_sunset": 1,
    }

    if q is not None and q != "":
        projection["score"] = {"$meta": "textScore"}
        query["$text"] = {"$search": q}

    if cat is not None:
        selected_cats = []
        for name, category in categories.items():
            if category["id"] in cat:
                selected_cats.append(name)
                category["selected"] = True
            else:
                category["selected"] = False
        query["web_scan.module_type"] = {"$in": selected_cats}
    else:
        for category in categories.values():
            category["selected"] = True

    if status is not None and status != "Any":
        query["web_scan.status"] = status

    cursor = mongo.db.fips.find(query, projection)

    if sort == "match" and q is not None and q != "":
        cursor.sort([("score", {"$meta": "textScore"}), ("web_scan.module_name", pymongo.ASCENDING)])
    elif sort == "number":
        cursor.sort([("cert_id", pymongo.ASCENDING)])
    elif sort == "first_cert_date":
        cursor.sort([("web_scan.date_validation.0", pymongo.ASCENDING)])
    elif sort == "last_cert_date":
        cursor.sort([("web_scan.date_validation", pymongo.ASCENDING)])
    elif sort == "sunset_date":
        cursor.sort([("web_scan.date_sunset", pymongo.ASCENDING)])
    elif sort == "level":
        cursor.sort([("web_scan.level", pymongo.ASCENDING)])
    elif sort == "vendor":
        cursor.sort([("web_scan.vendor", pymongo.ASCENDING)])
    return cursor, categories


def process_search(req, callback=None):
    page = int(req.args.get("page", 1))
    q = req.args.get("q", None)
    cat = req.args.get("cat", None)
    status = req.args.get("status", "Any")
    sort = req.args.get("sort", "match")

    cursor, categories = select_certs(q, cat, status, sort)

    per_page = current_app.config["SEARCH_ITEMS_PER_PAGE"]
    pagination = Pagination(
        page=page,
        per_page=per_page,
        search=True,
        found=cursor.count(),
        total=mongo.db.fips.count_documents({}),
        css_framework="bootstrap4",
        alignment="center",
        url_callback=callback,
    )
    return {
        "pagination": pagination,
        "certs": cursor[(page - 1) * per_page: page * per_page],
        "categories": categories,
        "q": q,
        "page": page,
        "status": status,
        "sort": sort,
    }


@fips.route("/search/")
@register_breadcrumb(fips, ".search", "Search")
def search():
    res = process_search(request)
    return render_template(
        "fips/search.html.jinja2",
        **res,
        title=f"FIPS 140 [{res['q']}] ({res['page']}) | seccerts.org",
    )


@fips.route("/search/pagination/")
def search_pagination():
    def callback(**kwargs):
        return url_for(".search", **kwargs)

    res = process_search(request, callback=callback)
    return render_template("fips/search_pagination.html.jinja2", **res)


@fips.route("/analysis/")
@register_breadcrumb(fips, ".analysis", "Analysis")
def analysis():
    return render_template("fips/analysis.html.jinja2")


@fips.route("/random/")
def rand():
    current_ids = list(map(itemgetter("_id"), mongo.db.fips.find({}, ["_id"])))
    return redirect(url_for(".entry", hashid=random.choice(current_ids)))


@fips.route("/<string(length=16):hashid>/")
@register_breadcrumb(fips, ".entry", "", dynamic_list_constructor=lambda *args, **kwargs: [{"text": request.view_args["hashid"]}])
def entry(hashid):
    with sentry_sdk.start_span(op="mongo", description="Find cert"):
        doc = mongo.db.fips.find_one({"_id": hashid})
    if doc:
        return render_template(
            "fips/entry.html.jinja2", cert=add_dots(doc), hashid=hashid
        )
    else:
        return abort(404)


@fips.route("/<string(length=16):hashid>/graph.json")
def entry_graph_json(hashid):
    with sentry_sdk.start_span(op="mongo", description="Find cert"):
        doc = mongo.db.fips.find_one({"_id": hashid})
    if doc:
        fips_map = get_fips_map()
        if hashid in fips_map.keys():
            network_data = node_link_data(fips_map[hashid])
        else:
            network_data = {}
        return send_json_attachment(network_data)
    else:
        return abort(404)


@fips.route("/<string(length=16):hashid>/cert.json")
def entry_json(hashid):
    with sentry_sdk.start_span(op="mongo", description="Find cert"):
        doc = mongo.db.fips.find_one({"_id": hashid})
    if doc:
        return send_json_attachment(add_dots(doc))
    else:
        return abort(404)


@fips.route("/id/<string:cert_id>")
def entry_id(cert_id):
    with sentry_sdk.start_span(op="mongo", description="Find cert"):
        doc = mongo.db.fips.find_one({"cert_id": cert_id})
    if doc:
        return redirect(url_for("fips.entry", hashid=doc["_id"]))
    else:
        return abort(404)


@fips.route("/name/<string:name>")
def entry_name(name):
    name = name.replace("_", " ")
    with sentry_sdk.start_span(op="mongo", description="Find cert"):
        doc = mongo.db.fips.find_one({"name": name})
    if doc:
        return redirect(url_for("fips.entry", hashid=doc["_id"]))
    else:
        return abort(404)
