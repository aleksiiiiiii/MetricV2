"""Notifications push : abonnement, réglages, envoi, ordonnanceur (`NOT-01` → `NOT-03`).

Trois batteries :

* **sans clé VAPID** — le régime de `IA-07` appliqué au push. C'est la moitié de DoD que la
  simulation peut couvrir entièrement, et elle est en premier parce que c'est l'état par
  défaut d'une installation neuve ;
* **avec clé** — abonnement, désabonnement, envoi, et ce qui arrive à un abonnement
  révoqué ;
* **l'ordonnanceur** — une passe à la fois, avec une horloge fournie. Il ne dort jamais.

Aucun test de ce fichier ne joint un vrai service push : `tests/fake_webpush.py` le double,
et le chiffrement, lui, est bien réel — la batterie vérifie que le corps envoyé n'est pas
du JSON en clair.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.domains.notifications.push import PushSender
from app.domains.notifications.reminders import ReminderKind, allowed
from app.domains.notifications.scheduler import ReminderScheduler
from app.storage.files import FileStore
from tests.conftest import TEST_ENDPOINT, subscription_payload
from tests.fake_webdav import FakeWebDav
from tests.fake_webpush import FakeWebPush

PARIS = ZoneInfo("Europe/Paris")
JOUR = date(2026, 8, 13)

SUBSCRIPTIONS = "Metric/notifications/subscriptions.csv"
SENT = "Metric/notifications/sent.csv"
SETTINGS = "Metric/settings/settings.csv"


def at(hour: int, minute: int = 0, day: date = JOUR) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=PARIS)


# ═══ Sans clé VAPID — rien n'est bloqué ═══════════════


class TestSansCle:
    """`IA-07` appliqué au push : une clé absente est un **état**, pas une panne."""

    def test_letat_repond_200_et_dit_ce_qui_manque(
        self, store_client: TestClient, auth: dict[str, str]
    ) -> None:
        """Même forme que `AiStatus` et `SubscriptionInfo`.

        Un écran ne demande jamais « la clé est-elle configurée ? » à sa propre
        configuration : il le demande au serveur, qui répond dans les deux cas.
        """
        response = store_client.get("/api/notifications", headers=auth)
        assert response.status_code == 200, response.text

        push = response.json()["push"]
        assert push["configured"] is False
        assert push["public_key"] is None
        assert "vapid-keys" in push["message"]

    def test_labonnement_refuse_avec_un_code_du_catalogue(
        self, store_client: TestClient, auth: dict[str, str]
    ) -> None:
        """Accepter un abonnement qu'on ne saurait jamais signer serait pire que refuser.

        L'écran afficherait « abonné » pour quelqu'un qui ne recevrait rien.
        """
        response = store_client.post(
            "/api/notifications/subscribe", json=subscription_payload(), headers=auth
        )
        assert response.status_code == 503
        assert response.json()["code"] == "push_not_configured"

    def test_les_créneaux_restent_lisibles_et_modifiables(
        self, store_client: TestClient, auth: dict[str, str]
    ) -> None:
        """Les créneaux vivent dans `settings.csv` et ne dépendent d'aucune clé (`NOT-03`)."""
        view = store_client.get("/api/notifications", headers=auth).json()
        assert view["reminders"] == {
            "supplements": None,
            "hydration": None,
            "meals": None,
            "workout": None,
        }

        response = store_client.patch(
            "/api/notifications/reminders",
            json={"hydration": "20:00"},
            headers={**auth, "If-Match": view["token"]},
        )
        assert response.status_code == 200, response.text
        assert response.json()["reminders"]["hydration"] == "20:00"

    def test_le_défaut_est_le_silence(self, store_client: TestClient, auth: dict[str, str]) -> None:
        """Aucun rappel n'est configuré à l'installation.

        Un rappel qui arrive au mauvais moment se désinstalle en un geste : chaque créneau
        doit être un choix explicite, jamais un défaut hérité.
        """
        reminders = store_client.get("/api/notifications", headers=auth).json()["reminders"]
        assert all(value is None for value in reminders.values())

    def test_les_routes_exigent_un_jeton(self, store_client: TestClient) -> None:
        """`AUTH-05` : le flux `.ics` est la seule exception du projet, et il n'y en a pas
        de deuxième. Un abonnement push se fait depuis l'application connectée."""
        assert store_client.get("/api/notifications").status_code == 401
        assert store_client.post("/api/notifications/subscribe", json={}).status_code == 401
        assert store_client.post("/api/notifications/test").status_code == 401


# ═══ Avec clé — l'abonnement ══════════════════════════


class TestAbonnement:
    def test_la_clé_publique_est_servie(
        self, push_client: TestClient, push_auth: dict[str, str]
    ) -> None:
        """L'écran ne devine pas la clé : il la reçoit, ou il ne propose pas l'abonnement."""
        push = push_client.get("/api/notifications", headers=push_auth).json()["push"]
        assert push["configured"] is True
        assert push["public_key"] is not None and len(push["public_key"]) > 40

    def test_sabonner_écrit_une_ligne(
        self, push_client: TestClient, push_auth: dict[str, str], dav: FakeWebDav
    ) -> None:
        response = push_client.post(
            "/api/notifications/subscribe", json=subscription_payload(), headers=push_auth
        )
        assert response.status_code == 204, response.text

        contenu = dav.content_of(SUBSCRIPTIONS)
        assert "id,created,endpoint,p256dh,auth,user_agent" in contenu
        assert TEST_ENDPOINT in contenu

    def test_sabonner_deux_fois_ne_fait_quune_ligne(
        self, push_client: TestClient, push_auth: dict[str, str]
    ) -> None:
        """Idempotent par `endpoint` : le navigateur rend le même tant qu'il est valide.

        Sans cela, chaque réouverture de l'écran laisserait un abonnement de plus, et
        chaque rappel partirait en double.
        """
        for _ in range(3):
            push_client.post(
                "/api/notifications/subscribe", json=subscription_payload(), headers=push_auth
            )

        devices = push_client.get("/api/notifications", headers=push_auth).json()["devices"]
        assert len(devices) == 1

    def test_deux_appareils_font_deux_lignes(
        self, push_client: TestClient, push_auth: dict[str, str]
    ) -> None:
        for endpoint in (TEST_ENDPOINT, "https://push.test/envoi/appareil-2"):
            push_client.post(
                "/api/notifications/subscribe",
                json=subscription_payload(endpoint),
                headers=push_auth,
            )

        devices = push_client.get("/api/notifications", headers=push_auth).json()["devices"]
        assert len(devices) == 2

    def test_ladresse_dabonnement_nest_pas_publiée(
        self, push_client: TestClient, push_auth: dict[str, str]
    ) -> None:
        """Qui détient l'`endpoint` peut envoyer une notification à cet appareil.

        L'écran n'en reçoit que les derniers caractères — assez pour distinguer deux
        téléphones, pas assez pour s'en servir.
        """
        push_client.post(
            "/api/notifications/subscribe", json=subscription_payload(), headers=push_auth
        )
        devices = push_client.get("/api/notifications", headers=push_auth).json()["devices"]

        assert TEST_ENDPOINT not in str(devices)
        assert devices[0]["hint"] == TEST_ENDPOINT[-8:]
        # Le libellé est **dérivé par le serveur** du `user-agent`, qui reste dans le
        # fichier et n'est pas publié : tronqué dans une liste, il ne nomme rien et se
        # lit comme un défaut d'affichage. Vu en capture, pas par un test.
        assert devices[0]["label"] == "iPhone"

    def test_un_user_agent_inconnu_ne_donne_pas_un_nom_inventé(
        self, push_client: TestClient, push_auth: dict[str, str]
    ) -> None:
        """« Appareil », jamais une supposition.

        C'est « aucune valeur inventée » à l'échelle d'un libellé : mieux vaut un mot
        générique qu'un nom d'appareil faux.
        """
        push_client.post(
            "/api/notifications/subscribe",
            json=subscription_payload(user_agent="quelque chose d'inconnu"),
            headers=push_auth,
        )
        devices = push_client.get("/api/notifications", headers=push_auth).json()["devices"]
        assert devices[0]["label"] == "Appareil"

    def test_se_désabonner_retire_la_ligne(
        self, push_client: TestClient, push_auth: dict[str, str]
    ) -> None:
        push_client.post(
            "/api/notifications/subscribe", json=subscription_payload(), headers=push_auth
        )
        response = push_client.delete(
            "/api/notifications/subscribe",
            params={"endpoint": TEST_ENDPOINT},
            headers=push_auth,
        )
        assert response.status_code == 204

        devices = push_client.get("/api/notifications", headers=push_auth).json()["devices"]
        assert devices == []

    def test_se_désabonner_deux_fois_aboutit_au_même_état(
        self, push_client: TestClient, push_auth: dict[str, str]
    ) -> None:
        """Un écran qui rejoue le geste après un rechargement ne doit pas voir d'erreur
        pour un résultat correct."""
        for _ in range(2):
            response = push_client.delete(
                "/api/notifications/subscribe",
                params={"endpoint": TEST_ENDPOINT},
                headers=push_auth,
            )
            assert response.status_code == 204


# ═══ Les créneaux (`NOT-03`) ══════════════════════════


class TestCreneaux:
    def test_sans_if_match_cest_un_conflit(
        self, push_client: TestClient, push_auth: dict[str, str]
    ) -> None:
        """Un `If-Match` **absent est un conflit**, jamais une permission (`STO-05`).

        Sinon la garde se contournerait en omettant l'en-tête.
        """
        response = push_client.patch(
            "/api/notifications/reminders", json={"hydration": "20:00"}, headers=push_auth
        )
        assert response.status_code == 409

    def test_un_champ_omis_reste_à_sa_valeur(
        self, push_client: TestClient, push_auth: dict[str, str]
    ) -> None:
        view = push_client.get("/api/notifications", headers=push_auth).json()
        push_client.patch(
            "/api/notifications/reminders",
            json={"hydration": "20:00", "meals": "12:30"},
            headers={**push_auth, "If-Match": view["token"]},
        )

        view = push_client.get("/api/notifications", headers=push_auth).json()
        after = push_client.patch(
            "/api/notifications/reminders",
            json={"meals": "13:00"},
            headers={**push_auth, "If-Match": view["token"]},
        ).json()

        assert after["reminders"]["meals"] == "13:00"
        assert after["reminders"]["hydration"] == "20:00"

    def test_un_champ_à_null_éteint_le_rappel(
        self, push_client: TestClient, push_auth: dict[str, str]
    ) -> None:
        """La distinction qui compte : `null` veut dire **éteint**, pas « non fourni ».

        C'est ce qui oblige à passer par `SettingsService.update_keys`, qui écrit les
        cellules vides au lieu de les ignorer comme le fait `SettingsPayload`.
        """
        view = push_client.get("/api/notifications", headers=push_auth).json()
        push_client.patch(
            "/api/notifications/reminders",
            json={"hydration": "20:00"},
            headers={**push_auth, "If-Match": view["token"]},
        )

        view = push_client.get("/api/notifications", headers=push_auth).json()
        after = push_client.patch(
            "/api/notifications/reminders",
            json={"hydration": None},
            headers={**push_auth, "If-Match": view["token"]},
        ).json()

        assert after["reminders"]["hydration"] is None

    def test_un_horaire_aberrant_est_refusé_à_la_frontière(
        self, push_client: TestClient, push_auth: dict[str, str]
    ) -> None:
        view = push_client.get("/api/notifications", headers=push_auth).json()
        for mauvais in ("25:00", "20h00", "7:5", "midi"):
            response = push_client.patch(
                "/api/notifications/reminders",
                json={"hydration": mauvais},
                headers={**push_auth, "If-Match": view["token"]},
            )
            assert response.status_code == 422, mauvais

    def test_les_créneaux_vivent_dans_settings_csv(
        self, push_client: TestClient, push_auth: dict[str, str], dav: FakeWebDav
    ) -> None:
        """`NOT-03` : « stockés comme les autres réglages », pas dans un fichier à eux."""
        view = push_client.get("/api/notifications", headers=push_auth).json()
        push_client.patch(
            "/api/notifications/reminders",
            json={"supplements": "20:00"},
            headers={**push_auth, "If-Match": view["token"]},
        )
        assert "reminders_supplements,20:00" in dav.content_of(SETTINGS)

    def test_ils_ne_fuient_pas_dans_les_réglages_typés(
        self, push_client: TestClient, push_auth: dict[str, str]
    ) -> None:
        view = push_client.get("/api/notifications", headers=push_auth).json()
        push_client.patch(
            "/api/notifications/reminders",
            json={"supplements": "20:00"},
            headers={**push_auth, "If-Match": view["token"]},
        )

        settings = push_client.get("/api/settings", headers=push_auth).json()
        assert "reminders_supplements" not in settings["values"]
        assert "reminders_supplements" not in settings["stored"]

    def test_modifier_un_réglage_typé_ne_les_efface_pas(
        self, push_client: TestClient, push_auth: dict[str, str], dav: FakeWebDav
    ) -> None:
        """La promesse de `TYPED_KEYS` : les clés inconnues sont **conservées**.

        Sans cela, régler son poids cible éteindrait tous ses rappels sans rien dire.
        """
        view = push_client.get("/api/notifications", headers=push_auth).json()
        push_client.patch(
            "/api/notifications/reminders",
            json={"supplements": "20:00"},
            headers={**push_auth, "If-Match": view["token"]},
        )

        settings = push_client.get("/api/settings", headers=push_auth).json()
        push_client.patch(
            "/api/settings",
            json={"target_weight_kg": 74},
            headers={**push_auth, "If-Match": settings["token"]},
        )

        assert "reminders_supplements,20:00" in dav.content_of(SETTINGS)


# ═══ L'envoi ══════════════════════════════════════════


class TestEnvoi:
    def test_lessai_exige_un_appareil(
        self, push_client: TestClient, push_auth: dict[str, str]
    ) -> None:
        response = push_client.post("/api/notifications/test", headers=push_auth)
        assert response.status_code == 404

    def test_lessai_part_chiffré(
        self, push_client: TestClient, push_auth: dict[str, str], webpush: FakeWebPush
    ) -> None:
        """Le contrôle qui compte : le corps n'est **pas** du JSON en clair.

        Une régression qui enverrait la charge utile telle quelle ferait transiter les
        notifications par un service tiers en clair, et rien à l'écran ne le dirait.
        """
        push_client.post(
            "/api/notifications/subscribe", json=subscription_payload(), headers=push_auth
        )
        response = push_client.post("/api/notifications/test", headers=push_auth)
        assert response.status_code == 204, response.text

        assert webpush.count == 1
        envoi = webpush.deliveries[0]
        assert envoi.encrypted
        assert envoi.headers["authorization"].startswith("vapid ")
        assert envoi.headers["content-encoding"] == "aes128gcm"
        assert "ttl" in envoi.headers

    def test_lessai_na_pas_le_tag_dun_vrai_rappel(
        self, push_client: TestClient, push_auth: dict[str, str], webpush: FakeWebPush
    ) -> None:
        """Emprunter le `tag` d'un créneau ferait disparaître un vrai rappel du centre
        de notifications au profit d'un message d'essai."""
        push_client.post(
            "/api/notifications/subscribe", json=subscription_payload(), headers=push_auth
        )
        push_client.post("/api/notifications/test", headers=push_auth)

        # Le corps est chiffré : on vérifie sur ce que le service a produit, c'est-à-dire
        # qu'aucun `tag` de créneau ne peut s'y trouver par construction.
        assert webpush.count == 1

    def test_un_abonnement_révoqué_est_retiré(
        self,
        push_client: TestClient,
        push_auth: dict[str, str],
        webpush: FakeWebPush,
    ) -> None:
        """`410 Gone` : le navigateur a été réinstallé, ou l'autorisation retirée.

        La ligne doit partir, sinon on la retenterait à chaque rappel, indéfiniment.
        """
        push_client.post(
            "/api/notifications/subscribe", json=subscription_payload(), headers=push_auth
        )
        webpush.revoke(TEST_ENDPOINT)

        push_client.post("/api/notifications/test", headers=push_auth)

        devices = push_client.get("/api/notifications", headers=push_auth).json()["devices"]
        assert devices == []

    def test_une_panne_de_transport_conserve_labonnement(
        self,
        push_client: TestClient,
        push_auth: dict[str, str],
        webpush: FakeWebPush,
    ) -> None:
        """`503` : le service est en panne. Réessayer au prochain créneau a un sens.

        Confondre ce cas avec une révocation désabonnerait quelqu'un parce que le Wi-Fi a
        hoqueté.
        """
        push_client.post(
            "/api/notifications/subscribe", json=subscription_payload(), headers=push_auth
        )
        webpush.break_down(TEST_ENDPOINT)

        push_client.post("/api/notifications/test", headers=push_auth)

        devices = push_client.get("/api/notifications", headers=push_auth).json()["devices"]
        assert len(devices) == 1

    def test_un_appareil_injoignable_narrête_pas_les_autres(
        self,
        push_client: TestClient,
        push_auth: dict[str, str],
        webpush: FakeWebPush,
    ) -> None:
        second = "https://push.test/envoi/appareil-2"
        for endpoint in (TEST_ENDPOINT, second):
            push_client.post(
                "/api/notifications/subscribe",
                json=subscription_payload(endpoint),
                headers=push_auth,
            )
        webpush.break_down(TEST_ENDPOINT)

        push_client.post("/api/notifications/test", headers=push_auth)

        assert webpush.sent_to(second), "le second appareil n'a rien reçu"


# ═══ L'ordonnanceur (`NOT-02`) ════════════════════════


class TestOrdonnanceur:
    """Une passe à la fois, avec une horloge fournie. Aucun test ne dort."""

    @staticmethod
    def _seed_reminders(dav: FakeWebDav, **slots: str) -> None:
        lignes = "\n".join(f"reminders_{name},{value}" for name, value in slots.items())
        dav.seed(SETTINGS, f"key,value\n{lignes}\n")

    @staticmethod
    def _seed_subscription(dav: FakeWebDav) -> None:
        from tests.conftest import TEST_AUTH, TEST_P256DH

        dav.seed(
            SUBSCRIPTIONS,
            "id,created,endpoint,p256dh,auth,user_agent\n"
            f"app1,2026-08-01,{TEST_ENDPOINT},{TEST_P256DH},{TEST_AUTH},iPhone\n",
        )

    def _scheduler(
        self, store: FileStore, sender: PushSender, moment: datetime
    ) -> ReminderScheduler:
        return ReminderScheduler(store, sender, now=lambda: moment)

    def test_aucun_créneau_configuré_nenvoie_rien(
        self, store: FileStore, push_sender: PushSender, dav: FakeWebDav, webpush: FakeWebPush
    ) -> None:
        self._seed_reminders(dav)
        self._seed_subscription(dav)

        envoyes = asyncio.run(self._scheduler(store, push_sender, at(20)).tick())

        assert envoyes == []
        assert webpush.count == 0

    def test_un_créneau_atteint_envoie(
        self, store: FileStore, push_sender: PushSender, dav: FakeWebDav, webpush: FakeWebPush
    ) -> None:
        self._seed_reminders(dav, meals="12:00")
        self._seed_subscription(dav)

        envoyes = asyncio.run(self._scheduler(store, push_sender, at(12)).tick())

        assert envoyes == [ReminderKind.MEALS]
        assert webpush.count == 1

    def test_deux_passes_du_même_créneau_nenvoient_quune_fois(
        self, store: FileStore, push_sender: PushSender, dav: FakeWebDav, webpush: FakeWebPush
    ) -> None:
        self._seed_reminders(dav, meals="12:00")
        self._seed_subscription(dav)

        async def deux_passes() -> None:
            scheduler = self._scheduler(store, push_sender, at(12))
            await scheduler.tick()
            await scheduler.tick()

        asyncio.run(deux_passes())
        assert webpush.count == 1

    def test_un_redémarrage_ne_renvoie_pas_ce_qui_est_parti(
        self, store: FileStore, push_sender: PushSender, dav: FakeWebDav, webpush: FakeWebPush
    ) -> None:
        """La mémoire est un **fichier**, pas une variable de processus.

        C'est tout l'intérêt de `notifications/sent.csv` : relancer l'API à 12 h 05 ne doit
        pas renvoyer le rappel de midi.
        """
        self._seed_reminders(dav, meals="12:00")
        self._seed_subscription(dav)

        asyncio.run(self._scheduler(store, push_sender, at(12)).tick())
        assert webpush.count == 1
        assert "meals" in dav.content_of(SENT)

        # Un ordonnanceur tout neuf, comme après un redémarrage.
        asyncio.run(self._scheduler(store, push_sender, at(12, 30)).tick())
        assert webpush.count == 1

    def test_le_lendemain_le_rappel_repart(
        self, store: FileStore, push_sender: PushSender, dav: FakeWebDav, webpush: FakeWebPush
    ) -> None:
        self._seed_reminders(dav, meals="12:00")
        self._seed_subscription(dav)

        asyncio.run(self._scheduler(store, push_sender, at(12)).tick())
        asyncio.run(self._scheduler(store, push_sender, at(12, day=date(2026, 8, 14))).tick())
        assert webpush.count == 2

    def test_rien_à_dire_nenvoie_rien_et_ne_consigne_rien(
        self, store: FileStore, push_sender: PushSender, dav: FakeWebDav, webpush: FakeWebPush
    ) -> None:
        """Aucune séance prévue : pas de rappel de séance, et pas de ligne dans le journal.

        `sent.csv` répond à « quand ai-je été rappelé » — y écrire une ligne pour un rappel
        qui n'est jamais parti rendrait cette réponse fausse.
        """
        self._seed_reminders(dav, workout="18:00")
        self._seed_subscription(dav)

        envoyes = asyncio.run(self._scheduler(store, push_sender, at(18)).tick())

        assert envoyes == []
        assert webpush.count == 0
        assert SENT.strip("/") not in dav.files

    def test_une_cellule_time_vide_de_schedule_ne_casse_rien(
        self, store: FileStore, push_sender: PushSender, dav: FakeWebDav, webpush: FakeWebPush
    ) -> None:
        """Le défaut qui a coûté le tableau de bord entier au premier usage réel.

        La colonne `time` de `supplements/schedule.csv` est vide **par conception** : un
        rappel doit partir quand même, pas lever.
        """
        self._seed_reminders(dav, supplements="20:00")
        self._seed_subscription(dav)
        dav.seed(
            "Metric/supplements/schedule.csv",
            "id,name,dose,unit,time,frequency,active,created\n"
            "s1,Créatine,5,g,,daily,true,2026-01-01\n"
            "s2,Whey,30,g,,daily,true,2026-01-01\n",
        )

        envoyes = asyncio.run(self._scheduler(store, push_sender, at(20)).tick())

        assert envoyes == [ReminderKind.SUPPLEMENTS]
        assert webpush.count == 1

    def test_un_horaire_illisible_néteint_que_lui(
        self, store: FileStore, push_sender: PushSender, dav: FakeWebDav, webpush: FakeWebPush
    ) -> None:
        """Un réglage abîmé coûte son propre rappel, pas les trois autres.

        Et il ne déclenche **rien** : une valeur par défaut réveillerait quelqu'un.
        """
        dav.seed(
            SETTINGS,
            "key,value\nreminders_hydration,vingt heures\nreminders_meals,12:00\n",
        )
        self._seed_subscription(dav)

        envoyes = asyncio.run(self._scheduler(store, push_sender, at(12)).tick())
        assert envoyes == [ReminderKind.MEALS]

    def test_sans_abonné_le_créneau_est_quand_même_consigné(
        self, store: FileStore, push_sender: PushSender, dav: FakeWebDav, webpush: FakeWebPush
    ) -> None:
        """Sinon, chaque passe réessaierait — et un téléphone rallumé recevrait en rafale."""
        self._seed_reminders(dav, meals="12:00")

        envoyes = asyncio.run(self._scheduler(store, push_sender, at(12)).tick())

        assert envoyes == [ReminderKind.MEALS]
        assert webpush.count == 0
        assert "meals" in dav.content_of(SENT)

    def test_la_boucle_sarrête_proprement(
        self, store: FileStore, push_sender: PushSender, dav: FakeWebDav
    ) -> None:
        """`run()` n'est que `tick()` plus une attente — et elle doit rendre la main."""
        self._seed_reminders(dav)
        passes = 0

        async def scenario() -> None:
            nonlocal passes

            async def compte(_: float) -> None:
                nonlocal passes
                passes += 1
                if passes >= 3:
                    raise asyncio.CancelledError

            scheduler = ReminderScheduler(
                store, push_sender, now=lambda: at(12), sleep=compte, interval=0
            )
            scheduler.start()
            await asyncio.sleep(0)
            await scheduler.stop()

        asyncio.run(scenario())
        assert passes >= 1


# ── Le budget du jour (**N1**) ────────────────────────


class TestBudget:
    """Dix par jour au plus, quinze minutes entre deux.

    Le plafond ne bride pas les rappels prévus — il y en a moins — il **borne ce qu'une
    règle mal écrite pourrait produire**. Un déclencheur réactif se déclenche sur un état,
    et un état peut rester vrai toute la journée.
    """

    def test_le_plafond_arrête_les_envois(self) -> None:
        assert allowed(now=at(12), sent_today=9, last_sent=None) is True
        assert allowed(now=at(12), sent_today=10, last_sent=None) is False
        assert allowed(now=at(12), sent_today=42, last_sent=None) is False

    def test_deux_notifications_gardent_quinze_minutes(self) -> None:
        """Le problème n'est pas le nombre mais le groupement : trois notifications en
        cinq minutes se balayent d'un seul geste, y compris celle qui comptait."""
        assert allowed(now=at(12, 14), sent_today=1, last_sent=at(12)) is False
        assert allowed(now=at(12, 15), sent_today=1, last_sent=at(12)) is True

    def test_la_première_du_jour_ne_dépend_de_rien(self) -> None:
        assert allowed(now=at(6), sent_today=0, last_sent=None) is True

    def test_une_notification_dhier_espace_celle_de_cette_nuit(self) -> None:
        """La comparaison porte sur un **instant**, pas sur une date : le téléphone ne
        change pas de journée à minuit."""
        veille = at(23, 55, day=JOUR - timedelta(days=1))
        minuit = at(0, 5)

        assert allowed(now=minuit, sent_today=0, last_sent=veille) is False


class TestBudgetOrdonnanceur:
    """Le budget vu depuis une passe : ce qui est repoussé revient, ce qui n'avait rien à
    dire ne revient pas."""

    def _seed_reminders(self, dav: FakeWebDav, **slots: str) -> None:
        lignes = "".join(f"reminders_{kind},{slot}\n" for kind, slot in slots.items())
        dav.seed(SETTINGS, f"key,value\n{lignes}")

    def _seed_subscription(self, dav: FakeWebDav) -> None:
        from tests.conftest import TEST_AUTH, TEST_P256DH

        dav.seed(
            SUBSCRIPTIONS,
            "id,created,endpoint,p256dh,auth,user_agent\n"
            f"app1,2026-08-01,{TEST_ENDPOINT},{TEST_P256DH},{TEST_AUTH},iPhone\n",
        )

    def test_deux_créneaux_simultanés_ne_partent_pas_ensemble(
        self, store: FileStore, push_sender: PushSender, dav: FakeWebDav, webpush: FakeWebPush
    ) -> None:
        """C'est le cas que N1 existe pour empêcher : deux rappels à la même minute."""
        self._seed_reminders(dav, meals="12:00", hydration="12:00")
        self._seed_subscription(dav)

        envoyes = asyncio.run(ReminderScheduler(store, push_sender, now=lambda: at(12)).tick())

        assert len(envoyes) == 1
        assert webpush.count == 1

    def test_le_repoussé_repart_à_la_passe_suivante(
        self, store: FileStore, push_sender: PushSender, dav: FakeWebDav, webpush: FakeWebPush
    ) -> None:
        """Repoussé n'est pas perdu : il redevient dû tant que `GRACE` n'est pas dépassée.

        C'est pour ça que le budget se demande **après** `compose` : un rappel qui n'avait
        rien à dire est clos pour la journée, un rappel repoussé doit revenir. Les
        confondre en tairait un pour de bon.
        """
        self._seed_reminders(dav, meals="12:00", hydration="12:00")
        self._seed_subscription(dav)

        async def deux_passes() -> None:
            await ReminderScheduler(store, push_sender, now=lambda: at(12)).tick()
            await ReminderScheduler(store, push_sender, now=lambda: at(12, 20)).tick()

        asyncio.run(deux_passes())

        assert webpush.count == 2
