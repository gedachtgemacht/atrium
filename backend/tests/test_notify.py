"""Notifications: socket events for people online, emails for people offline, guests only on request.
Emails never carry message text."""

import email
from email import policy as email_policy

from .conftest import channels, drain, guest, login

SECRET = "MAILTEXT-55c1"


def outbox(client) -> list:
    d = client.app.state.atrium.settings.data_dir / "outbox"
    if not d.exists():
        return []
    return [email.message_from_bytes(p.read_bytes(), policy=email_policy.default) for p in sorted(d.glob("*.eml"))]


def body(m) -> str:
    return m.get_body(("plain",)).get_content()


def test_customer_message_emails_offline_members_without_content(client, sarah):
    sarah.post("/g/api/messages", json={"body": f"Urgent {SECRET}"})
    drain(client)
    mails = outbox(client)
    assert sorted(m["To"] for m in mails) == ["lena@kessler.example", "tom@kessler.example"]
    for m in mails:
        assert "Sarah Hollmann" in m["Subject"]
        assert SECRET not in m.as_string()
        assert "/#/c/" in body(m)


def test_online_people_get_a_socket_event_instead(client, lena, sarah):
    with lena.ws("/ws") as ws:
        ws.receive_json()
        sarah.post("/g/api/messages", json={"body": "Hello there"})
        while (e := ws.receive_json())["type"] != "notify":
            pass
        assert e["kind"] == "customer" and e["who"] == "Sarah Hollmann" and e["body"] == "Hello there"
    drain(client)
    assert [m["To"] for m in outbox(client)] == ["tom@kessler.example"]


def test_mentions_reach_the_right_person(client, lena):
    ch = channels(lena)
    lena.post(f"/api/channels/{ch['dispatch']['id']}/messages", json={"body": "@Tom can you check Thursday? @Nobody too"})
    drain(client)
    assert [m["To"] for m in outbox(client)] == ["tom@kessler.example"]
    assert "mentioned you in #dispatch" in body(outbox(client)[0])


def test_people_can_turn_emails_off_and_choose_a_language(client, lena, sarah):
    tom = login(client, "tom")
    me = tom.patch("/api/me", json={"notify_email": False, "locale": "de"}).json()
    assert me["notify_email"] is False and me["language"] == "de"
    sarah.post("/g/api/messages", json={"body": "Hi"})
    drain(client)
    assert [m["To"] for m in outbox(client)] == ["lena@kessler.example"]


def test_agent_finishing_notifies_whoever_asked(client, lena):
    tom = login(client, "tom")
    sales = channels(lena)["sales"]
    lena.post(f"/api/channels/{sales['id']}/messages", json={"body": "@QuoteAgent anything for me?"})
    drain(client)
    mails = outbox(client)
    assert [m["To"] for m in mails] == ["lena@kessler.example"]
    assert "Quote agent finished your request" in body(mails[0])
    assert tom  # Tom isn't in #sales and gets nothing


def test_guest_emails_only_on_request_with_login_and_unsubscribe(client, lena, seeded):
    shared = channels(lena)["Hollmann Bau"]
    lena.post(f"/api/channels/{shared['id']}/messages", json={"body": "Nobody asked for mail yet"})
    drain(client)
    assert outbox(client) == []

    inv = lena.post(f"/api/channels/{shared['id']}/guests", json={}).json()
    token = inv["link"].split("/g/")[1].split("#")[0]
    client.cookies.clear()
    r = client.post("/g/api/session", json={"token": token, "name": "Petra Lang", "email": "petra@hollmann.example", "locale": "de"},
                    headers={"X-Requested-With": "atrium"})
    me = r.json()
    assert me["email"] == "petra@hollmann.example" and me["notify"] is True and me["locale"] == "de"

    lena.post(f"/api/channels/{shared['id']}/messages", json={"body": f"Here you go {SECRET}"})
    drain(client)
    [m] = outbox(client)
    assert m["To"] == "petra@hollmann.example"
    assert m["Subject"] == "Neue Nachricht von Kessler Logistik"
    assert SECRET not in m.as_string()
    assert m["List-Unsubscribe"]
    text = body(m)
    login_token = text.split("#login=")[1].split()[0]
    unsub = text.split("/g/api/unsubscribe/")[1].split()[0]

    client.cookies.clear()
    resumed = client.post("/g/api/resume", json={"token": login_token}, headers={"X-Requested-With": "atrium"})
    assert resumed.status_code == 200 and resumed.json()["name"] == "Petra Lang"
    assert client.get("/g/api/messages", headers={"Cookie": f"atrium_guest={login_token}"}).status_code == 200

    client.cookies.clear()
    page = client.get(f"/g/api/unsubscribe/{unsub}")
    assert "keine E-Mails mehr" in page.text
    lena.post(f"/api/channels/{shared['id']}/messages", json={"body": "Again"})
    drain(client)
    assert len(outbox(client)) == 1


def test_guest_can_change_email_later_and_bad_addresses_are_refused(client, sarah):
    assert sarah.patch("/g/api/me", json={"email": "not-an-address"}).status_code == 400
    me = sarah.patch("/g/api/me", json={"email": "sarah@hollmann.example"}).json()
    assert me["notify"] is True
    me = sarah.patch("/g/api/me", json={"notify": False}).json()
    assert me["notify"] is False and me["email"] == "sarah@hollmann.example"
    assert sarah.patch("/g/api/me", json={"email": ""}).json()["email"] is None


def test_coming_back_before_the_email_cancels_it(client, lena, sarah):
    client.app.state.atrium.settings.notify_delay_seconds = 30
    sarah.post("/g/api/messages", json={"body": "Ping"})
    with lena.ws("/ws") as ws:
        ws.receive_json()
    client.app.state.atrium.settings.notify_delay_seconds = 0
    pending = client.app.state.atrium.notifier.users
    assert all(k != lena.get("/api/me").json()["id"] for k in map(str, pending))
    for p in list(pending.values()):
        p.task.cancel()
    drain(client)
    assert all(m["To"] != "lena@kessler.example" for m in outbox(client))
