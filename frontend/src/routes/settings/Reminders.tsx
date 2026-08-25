import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';

import { Badge, Button, Card, Empty, Field, Rule } from '@/components/ui';
import {
  notificationsApi,
  type NotificationsView,
  type ReminderKind,
  type RemindersPayload,
} from '@/features/notifications/api';
import { ApiError } from '@/lib/api';
import { cx } from '@/lib/cx';
import {
  currentEndpoint,
  pushSupport,
  subscribeThisDevice,
  unsubscribeThisDevice,
  type PushSupport,
} from '@/lib/push';
import { keys } from '@/lib/query';
import { useToast } from '@/lib/toast';

import styles from './Reminders.module.css';

/**
 * Les rappels (`NOT-01`, `NOT-03`) — une section de `/reglages`, pas un écran.
 *
 * La barre de navigation a été tranchée au lot L14b : cinq cibles en bas, le reste dans
 * la feuille « Plus ». Un écran de plus pour quatre horaires et un bouton d'abonnement
 * n'aurait pas payé sa place, et ces réglages répondent à la même question que le reste
 * de l'écran — « qu'est-ce que je vise ? ».
 *
 * ── Ce que cette section ne fait jamais ───────────────────────────────────
 *
 * **Elle n'invente aucun horaire.** Aucun créneau n'est proposé, aucun n'est coché
 * d'avance : le défaut est le silence, et il vient du serveur. Un rappel qui arrive au
 * mauvais moment se désinstalle en un geste et ne revient jamais — c'est la
 * fonctionnalité la plus facile à rendre nuisible du projet, et le seul garde-fou qui
 * tienne est que chaque créneau soit un choix explicite.
 *
 * **Elle ne décide pas si le push est disponible.** L'état vient du serveur
 * (`push.configured`, et la phrase à afficher), comme pour l'assistance IA et
 * l'abonnement iCal. Ce que le client détermine lui-même est d'un autre ordre : ce que
 * *ce navigateur-ci* sait faire — voir `lib/push.ts`.
 */

interface Spec {
  kind: ReminderKind;
  label: string;
  hint: string;
  /** Vrai quand le type porte **plusieurs** créneaux, séparés par des virgules. */
  many?: boolean;
}

/**
 * Les cinq rappels de `NOT-02` et de **N2**, et ce qu'ils disent.
 *
 * Les descriptions reprennent **mot pour mot** la règle du serveur : un rappel dit ce qui
 * n'est pas noté, jamais ce qui n'a pas été fait. L'écran doit l'annoncer avant que
 * l'utilisateur ne choisisse un horaire — sinon il attend « tu n'as pas bu », reçoit
 * autre chose, et le trouve mou.
 */
const REMINDERS: readonly Spec[] = [
  {
    kind: 'supplements',
    label: 'Suppléments',
    hint: 'Nomme ce qui n’est pas encore noté, et rien d’autre',
  },
  {
    kind: 'hydration',
    label: 'Hydratation',
    // Le texte dit **les deux conditions**, parce qu'un contrôle qui ne part pas se lit
    // comme un réglage cassé si l'on ignore la seconde.
    hint: 'Plusieurs heures, séparées par des virgules · ne part que si l’écart est important',
    many: true,
  },
  { kind: 'meals', label: 'Repas', hint: 'Ne part que si aucun repas n’est noté du jour' },
  {
    kind: 'protein',
    label: 'Protéines',
    hint: 'Cite ce qu’il reste, s’il reste un écart qu’un repas peut combler',
  },
  {
    kind: 'workout',
    label: 'Séance',
    hint: 'Uniquement les jours où une séance est au planning',
  },
];

/** Créneaux saisis. La chaîne vide **est** l'extinction, comme la cellule vide du fichier. */
type Draft = Record<ReminderKind, string>;

function toDraft(view: NotificationsView): Draft {
  return {
    supplements: view.reminders.supplements ?? '',
    hydration: view.reminders.hydration ?? '',
    meals: view.reminders.meals ?? '',
    workout: view.reminders.workout ?? '',
    protein: view.reminders.protein ?? '',
  };
}

/**
 * Ce que le formulaire envoie : **seulement ce qui a changé**.
 *
 * Un champ vidé part à `null`, ce qui éteint le rappel côté serveur. Un champ inchangé
 * n'est pas envoyé du tout — envoyer les quatre à chaque enregistrement écrirait quatre
 * cellules là où une seule a bougé, et rendrait toute écriture concurrente conflictuelle
 * pour rien.
 */
function changes(draft: Draft, view: NotificationsView): RemindersPayload {
  const before = toDraft(view);
  const payload: RemindersPayload = {};

  for (const { kind } of REMINDERS) {
    if (draft[kind] === before[kind]) continue;
    payload[kind] = draft[kind] === '' ? null : draft[kind];
  }
  return payload;
}

/** Ce que ce navigateur-ci sait faire, en une phrase — jamais un simple « impossible ». */
const SUPPORT_MESSAGE: Record<Exclude<PushSupport, 'ok'>, string> = {
  'needs-install':
    'Sur iPhone, les rappels demandent que Metric soit ajoutée à l’écran d’accueil : ' +
    'Partager, puis « Sur l’écran d’accueil ». Rouvre l’application depuis l’icône, et reviens ici.',
  insecure:
    'Cette adresse n’est pas un contexte sécurisé. Les rappels demandent HTTPS, ou localhost.',
  unsupported: 'Ce navigateur ne sait pas recevoir de notifications.',
};

function Devices({ view }: { view: NotificationsView }) {
  if (view.devices.length === 0) return null;

  return (
    <ul className={styles.devices}>
      {view.devices.map((device) => (
        <li key={device.id} className={styles.device}>
          <span className={styles.deviceName}>{device.label}</span>
          {/* Les derniers caractères de l'adresse, jamais l'adresse : qui la détient peut
              envoyer une notification à cet appareil. */}
          <span className={cx(styles.deviceHint, 'num')}>…{device.hint}</span>
        </li>
      ))}
    </ul>
  );
}

export function Reminders() {
  const client = useQueryClient();
  const { notify } = useToast();

  const { data, isPending, error } = useQuery({
    queryKey: keys.notifications.view(),
    queryFn: notificationsApi.read,
  });

  const [draft, setDraft] = useState<Draft | null>(null);
  const [refusal, setRefusal] = useState<ApiError | null>(null);
  // L'abonnement de **ce** navigateur : le serveur connaît la liste des appareils, il ne
  // sait pas lequel est celui qu'on a sous les yeux.
  const [endpoint, setEndpoint] = useState<string | null>(null);
  const [support] = useState<PushSupport>(() => pushSupport());

  useEffect(() => {
    void currentEndpoint().then(setEndpoint);
  }, []);

  /**
   * Écrire les créneaux change le jeton de `settings.csv`.
   *
   * Les deux sections de l'écran éditent le **même fichier** : sans cette invalidation,
   * la section « Objectifs » garderait un jeton périmé et son prochain enregistrement
   * partirait en `409` sans que rien ne l'explique.
   */
  const refresh = (updated?: NotificationsView) => {
    if (updated) client.setQueryData(keys.notifications.view(), updated);
    else void client.invalidateQueries({ queryKey: keys.notifications.all() });
    void client.invalidateQueries({ queryKey: keys.settings.all() });
  };

  const save = useMutation({
    mutationFn: (view: NotificationsView) =>
      notificationsApi.updateReminders(changes(draft ?? toDraft(view), view), view.token),

    onSuccess: (updated) => {
      refresh(updated);
      setDraft(null);
      setRefusal(null);
      notify('Rappels enregistrés.', 'effort');
    },

    onError: (caught: unknown) => {
      setRefusal(caught instanceof ApiError ? caught : null);
      // Le client décide sur le **code**, jamais sur le message (`API-07`).
      if (caught instanceof ApiError && caught.code === 'conflict') {
        refresh();
        setDraft(null);
      }
      notify(caught instanceof ApiError ? caught.message : 'Enregistrement impossible.', 'recover');
    },
  });

  const subscribe = useMutation({
    mutationFn: async (publicKey: string) => {
      const subscription = await subscribeThisDevice(publicKey);
      if (subscription === null) return null;
      await notificationsApi.subscribe(subscription);
      return subscription.endpoint;
    },
    onSuccess: (created) => {
      if (created === null) {
        // Un refus d'autorisation **est une réponse**, pas une panne : il ne casse rien,
        // et le dire vaut mieux qu'un message d'erreur rouge.
        notify('Les notifications sont refusées pour ce site.', 'load');
        return;
      }
      setEndpoint(created);
      refresh();
      notify('Cet appareil recevra les rappels.', 'effort');
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Abonnement impossible.', 'recover');
    },
  });

  const unsubscribe = useMutation({
    mutationFn: async () => {
      const removed = await unsubscribeThisDevice();
      if (removed !== null) await notificationsApi.unsubscribe(removed);
    },
    onSuccess: () => {
      setEndpoint(null);
      refresh();
      notify('Cet appareil ne recevra plus de rappels.', 'signal');
    },
  });

  const essai = useMutation({
    mutationFn: notificationsApi.test,
    onSuccess: () => {
      notify('Essai envoyé.', 'effort');
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Essai impossible.', 'recover');
    },
  });

  if (isPending) {
    return (
      <>
        <Rule>Rappels</Rule>
        <Card>chargement…</Card>
      </>
    );
  }

  if (error || !data) {
    return (
      <>
        <Rule>Rappels</Rule>
        <Card>
          <Empty title="Rappels indisponibles">
            {error instanceof Error ? error.message : 'Le serveur n’a pas répondu.'}
          </Empty>
        </Card>
      </>
    );
  }

  const fields = draft ?? toDraft(data);
  const dirty = Object.keys(changes(fields, data)).length > 0;
  const subscribed = endpoint !== null;

  return (
    <>
      <Rule>Rappels</Rule>

      <Card>
        <div className="spread">
          <span className={styles.name}>Notifications</span>
          <Badge tone={data.push.configured ? 'signal' : 'load'}>
            {data.push.configured ? 'disponibles' : 'non configurées'}
          </Badge>
        </div>

        {/* Le message vient du serveur, en français, et s'affiche tel quel (`API-07`). */}
        <p className={cx(styles.note, styles.noteSpaced)}>{data.push.message}</p>

        {data.push.configured && support !== 'ok' && (
          <p className={styles.note}>{SUPPORT_MESSAGE[support]}</p>
        )}

        <Devices view={data} />

        {data.push.configured && support === 'ok' && (
          <div className={styles.actions}>
            {subscribed ? (
              <>
                <Button
                  variant="quiet"
                  busy={unsubscribe.isPending}
                  onClick={() => {
                    unsubscribe.mutate();
                  }}
                >
                  Ne plus recevoir ici
                </Button>
                <Button
                  variant="ghost"
                  busy={essai.isPending}
                  onClick={() => {
                    essai.mutate();
                  }}
                >
                  Envoyer un essai
                </Button>
              </>
            ) : (
              <Button
                variant="primary"
                busy={subscribe.isPending}
                onClick={() => {
                  // La clé publique vient du serveur : sans elle, on ne propose rien.
                  if (data.push.public_key) subscribe.mutate(data.push.public_key);
                }}
              >
                Recevoir les rappels ici
              </Button>
            )}
          </div>
        )}
      </Card>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate(data);
        }}
        noValidate
      >
        {refusal !== null && refusal.fields.length === 0 && (
          <p className={styles.error} role="alert">
            {refusal.message}
          </p>
        )}

        <p className={cx(styles.note, styles.lede)}>
          Un rappel dit ce qui n’est <strong>pas noté</strong>, jamais ce qui n’a pas été fait —
          l’application sait seulement ce qu’elle a reçu. Laisse un horaire vide pour éteindre le
          rappel ; c’est l’état par défaut.
        </p>

        <div className="grid g2">
          {REMINDERS.map((spec) => (
            <Card key={spec.kind}>
              <div className="spread">
                <span className={styles.name}>{spec.label}</span>
                {/* Le badge dit l'**état du réglage**, et deux versions ont été écartées
                    en regardant la page :
                    — « 20:00 » répétait l'heure que le champ affiche trente pixels plus
                      bas, la même redite qu'« 2,4 sur 3 séances · séances par semaine »
                      au lot L14 ;
                    — « actif » était carrément **faux** sans clé VAPID : un créneau réglé
                      n'y déclenche rien, et l'écran aurait affirmé le contraire.
                    « réglé » est vrai dans les deux cas, et c'est déjà le mot que la
                    section « Objectifs » emploie plus haut sur le même écran. */}
                <Badge tone={fields[spec.kind] === '' ? 'load' : 'effort'}>
                  {fields[spec.kind] === '' ? 'éteint' : 'réglé'}
                </Badge>
              </div>
              <div className={styles.row}>
                {/* Un champ texte pour l'hydratation : `type="time"` ne sait porter
                    qu'une heure, et elle en a trois. Le format à virgules est celui des
                    raccourcis d'hydratation sur le même écran — un réglage à plusieurs
                    valeurs se lit et se corrige de la même façon partout. */}
                <Field
                  type={spec.many === true ? 'text' : 'time'}
                  inputMode={spec.many === true ? 'numeric' : undefined}
                  placeholder={spec.many === true ? '14:00, 18:00, 22:30' : undefined}
                  label={spec.many === true ? 'Heures du rappel' : 'Heure du rappel'}
                  // **Le nom accessible désigne quel rappel.** Cinq champs intitulés
                  // « Heure du rappel » sur le même écran s'entendent tous pareil à la
                  // synthèse vocale — c'est la leçon des pastilles « Corriger » du
                  // catalogue. L'étiquette visible reste courte : la carte porte déjà le
                  // sujet trente pixels plus haut, et le répéter serait la redite qu'on
                  // écarte ailleurs sur cet écran.
                  aria-label={`${spec.many === true ? 'Heures' : 'Heure'} du rappel — ${spec.label}`}
                  value={fields[spec.kind]}
                  error={refusal?.messageFor(spec.kind)}
                  hint={spec.hint}
                  onChange={(event) => {
                    const value = event.target.value;
                    setDraft((current) => ({ ...(current ?? toDraft(data)), [spec.kind]: value }));
                  }}
                />
              </div>
            </Card>
          ))}
        </div>

        <div className={styles.actions}>
          <Button type="submit" variant="primary" busy={save.isPending} disabled={!dirty}>
            Enregistrer les rappels
          </Button>
          {dirty && (
            <Button
              variant="quiet"
              onClick={() => {
                setDraft(null);
              }}
            >
              Annuler
            </Button>
          )}
        </div>
      </form>
    </>
  );
}
