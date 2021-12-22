from flask.testing import FlaskClient


def test_index(client: FlaskClient):
    resp = client.get("/fips/")
    assert resp.status_code == 200


def test_network(client: FlaskClient):
    resp = client.get("/fips/network/")
    assert resp.status_code == 200
    resp = client.get("/fips/network/graph.json")
    assert resp.status_code == 200


def test_analysis(client: FlaskClient):
    resp = client.get("/fips/analysis/")
    assert resp.status_code == 200


def test_search_basic(client: FlaskClient):
    cert_id = "310"
    cert_name = "MOVEit Crypto"
    resp = client.get(f"/fips/search/?q={cert_id}&cat=abcde&status=Any&sort=match")
    assert resp.status_code == 200
    assert cert_name in resp.data.decode()
    resp = client.get(f"/fips/search/?q={cert_id}&cat=abcde&status=Active&sort=match")
    assert resp.status_code == 200
    assert cert_name not in resp.data.decode()


def test_random(client: FlaskClient):
    for _ in range(100):
        resp = client.get("/fips/random/", follow_redirects=True)
        assert resp.status_code == 200


def test_entry(client: FlaskClient):
    hashid = "3465020c4414cd8c"
    cert_id = "310"
    cert_name = "MOVEit Crypto"
    hid_resp = client.get(f"/fips/{hashid}/", follow_redirects=True)
    assert hid_resp.status_code == 200
    cid_resp = client.get(f"/fips/id/{cert_id}", follow_redirects=True)
    assert cid_resp.status_code == 200
    assert len(cid_resp.history) == 1
    assert cid_resp.history[0].location.endswith(f"/fips/{hashid}/")
    graph_resp = client.get(f"/fips/{hashid}/graph.json")
    assert graph_resp.status_code == 200
    assert graph_resp.is_json
    cert_resp = client.get(f"/fips/{hashid}/cert.json")
    assert cert_resp.status_code == 200
    assert cert_resp.is_json
