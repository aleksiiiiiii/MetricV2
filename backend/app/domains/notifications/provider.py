"""Cycle de vie du push et de l'ordonnanceur (`NOT-01`, `NOT-02`).

**Même forme que `AiProvider`, et pour la même raison** : l'expéditeur détient un pool de
connexions keep-alive, il doit naître dans la boucle d'événements et être relâché à
l'arrêt.

Sans paire de clés VAPID, le fournisseur reste **inerte** : l'application démarre, tous les
écrans fonctionnent, l'ordonnanceur ne tourne pas, et la section « Rappels » de `/reglages`
dit ce qui manque. C'est `IA-07` appliqué au push — une clé absente est un **état**, pas
une panne.

Une condition de plus que pour l'IA, et elle a une raison : l'ordonnanceur ne démarre que
si le **stockage** est lui aussi configuré. Il lit des fichiers à chaque passe ; sans
Nextcloud, il ne ferait que journaliser une erreur toutes les minutes, indéfiniment.
"""

from __future__ import annotations

from app.config import Settings
from app.domains.notifications.push import PushSender
from app.domains.notifications.scheduler import ReminderScheduler
from app.storage.provider import StorageProvider


class PushProvider:
    """Détient l'expéditeur push et l'ordonnanceur, pour toute la vie du processus."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._sender: PushSender | None = None
        self._scheduler: ReminderScheduler | None = None

    @property
    def enabled(self) -> bool:
        return self._sender is not None

    @property
    def sender(self) -> PushSender | None:
        return self._sender

    @property
    def public_key(self) -> str | None:
        """Clé publique servie à l'écran. `null` tant qu'il n'y en a pas."""
        return self._sender.public_key if self._sender else None

    @property
    def message(self) -> str:
        """Ce qu'il y a à dire à l'écran sur l'état des notifications, en français."""
        if self.enabled:
            # Ce message dit un **état de configuration**, et rien d'autre. Il portait
            # aussi la règle — « un rappel ne dit jamais ce que tu n'as pas fait » — que
            # l'écran répète quatre cents pixels plus bas, à sa place : juste avant de
            # choisir un horaire. Deux fois la même phrase sur la même vue, c'est la
            # redite que le lot L14 avait déjà produite, et elle s'est vue en capture.
            return (
                "Les notifications sont configurées côté serveur. Chaque appareil doit "
                "ensuite être autorisé une fois, depuis lui-même."
            )
        return (
            "Aucune clé de notification n'est configurée : les rappels sont hors service. "
            "Génère une paire avec « make vapid-keys »."
        )

    async def start(self, storage: StorageProvider) -> None:
        if not self._settings.push_enabled:
            return

        self._sender = PushSender(
            public_key=self._settings.vapid_public_key.strip(),
            private_key=self._settings.vapid_private_key.strip(),
            subject=self._settings.vapid_subject.strip(),
        )

        # Sans stockage, l'ordonnanceur n'aurait aucun fichier à lire : il journaliserait
        # une erreur par minute sans jamais pouvoir envoyer quoi que ce soit.
        if self._settings.storage_configured:
            self._scheduler = ReminderScheduler(storage.store, self._sender)
            self._scheduler.start()

    def use(self, sender: PushSender) -> None:
        """Injecte un expéditeur déjà construit — utilisé par les tests.

        L'ordonnanceur n'est **pas** démarré : une batterie qui laisserait tourner une
        boucle de fond verrait ses envois arriver au milieu d'autres tests. Les tests
        d'ordonnanceur construisent le leur et appellent `tick()` eux-mêmes.
        """
        self._sender = sender

    async def stop(self) -> None:
        if self._scheduler is not None:
            await self._scheduler.stop()
            self._scheduler = None
        if self._sender is not None:
            await self._sender.aclose()
            self._sender = None


__all__ = ["PushProvider"]
