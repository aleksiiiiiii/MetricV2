/**
 * L'assistant (`IA-09` → `IA-16`).
 *
 * Un écran de discussion, et rien d'autre : la hauteur entière, un fil qui défile, une
 * saisie collée en bas. Ce qui vivait au-dessous — le carnet, ses formulaires — est passé
 * dans des feuilles. Un chat dont il faut faire défiler la page pour retrouver le champ
 * n'est pas un chat, c'est un formulaire avec un historique.
 *
 * ## Ce que cet écran ne décide pas
 *
 * Il ne construit aucun contexte : le condensé est assemblé **par le serveur**, à partir
 * des services qui en détiennent chacun la règle. Il ne décide pas non plus de ce qui
 * mérite d'être retenu ni de ce qui s'écrit dans les données — le carnet se remplit côté
 * serveur, les actions y sont validées et exécutées. Cet écran reçoit un compte rendu et
 * offre le geste qui va avec : annuler un ajout, confirmer un changement, oublier une note.
 *
 * ## Le fil vit sur le serveur
 *
 * Il n'y vivait pas : cet écran rendait l'historique à chaque question et le perdait au
 * rechargement. Depuis que la conversation peut **écrire**, le passé ne peut plus venir de
 * l'appelant — un client fabriquerait sinon le passé qui justifie l'action qu'il veut voir
 * prendre. L'écran ne rend donc qu'un identifiant de fil, et le serveur lit le reste.
 *
 * ## La hauteur, et pourquoi `dvh`
 *
 * L'écran occupe ce que la coquille lui laisse, calculé une fois en CSS. `100dvh` et non
 * `100vh` : sur iOS, le clavier système réduit le viewport **dynamique**, si bien que la
 * saisie remonte avec lui sans une ligne de JavaScript. Avec `vh`, elle resterait sous le
 * clavier — le défaut classique des interfaces de discussion sur téléphone.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router';

import {
  Badge,
  Button,
  Chip,
  ChipStrip,
  Empty,
  ExternalLinkButton,
  Field,
  Markdown,
  Sheet,
  SheetGroup,
  SheetRow,
} from '@/components/ui';
import { IconBook, IconThreads } from '@/components/ui/icons';
import { activityApi } from '@/features/activity/api';
import { useAiStatus } from '@/features/ai/useAiStatus';
import {
  assistantApi,
  type ActionReport,
  type MemoryEntry,
  type UndoRef,
} from '@/features/assistant/api';
import { ApiError } from '@/lib/api';
import { cx } from '@/lib/cx';
import { plural, shortDate } from '@/lib/format';
import { keys } from '@/lib/query';
import { useToast } from '@/lib/toast';

import styles from './Assistant.module.css';
import { CircuitCard } from './activity/CircuitCard';

/** Une question, sa réponse, et ce que l'assistant a fait à ce tour-là. */
interface Exchange {
  question: string;
  reply: string;
  actions: ActionReport[];
  remembered: MemoryEntry[];
  /**
   * Le condensé envoyé au modèle **pour ce tour-là**.
   *
   * Il vivait dans un état d'écran, unique, remplacé à chaque question : le `<details>`
   * n'existait donc que sur le dernier échange et disparaissait dès le suivant. On ne
   * pouvait plus vérifier sur quoi s'appuyait une réponse d'il y a trois tours, ce qui
   * vide `IA-09` de ce qui le rendait vérifiable.
   */
  context: string[];
  /** Le message du serveur quand le tour a échoué. La question reste rejouable. */
  failure?: string;
}

function useInvalidateMemory() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: keys.assistant.all() });
  };
}

// ── Ce que l'assistant a fait, ou demande à faire (`IA-15`) ──

/**
 * Une action, avec le geste qui va avec.
 *
 * Trois états, trois discours, et la différence entre eux est ce qui rend le lot tenable :
 *
 * * `done` — c'est écrit. Un bouton défait, en appelant la route du domaine : le geste
 *   que l'utilisateur ferait lui-même depuis l'écran concerné.
 * * `pending` — **rien n'est écrit**. L'action dit ce qu'elle changerait, et deux boutons
 *   tranchent. Le projet n'a pas de corbeille : effacer se demande.
 * * `refused` — rien n'a eu lieu, et la phrase dit pourquoi. Elle vient du serveur, en
 *   français, et s'affiche telle quelle.
 */
function ActionCard({ report }: { report: ActionReport }) {
  const client = useQueryClient();
  const { notify } = useToast();
  const [settled, setSettled] = useState<'undone' | 'confirmed' | 'dismissed' | null>(null);

  /**
   * Le circuit que cette action a créé, tel qu'il est **maintenant**.
   *
   * La liste n'est demandée que si l'action en a produit un : les autres cartes ne paient
   * pas une requête pour rien. Le rapprochement se fait sur l'identifiant stable — une
   * position se décale, un identifiant non — et un circuit supprimé depuis ne se retrouve
   * pas, donc « Fait » disparaît de lui-même plutôt que d'échouer à l'appui.
   */
  const { data: circuits } = useQuery({
    queryKey: keys.activity.circuits(),
    queryFn: activityApi.circuits,
    enabled: report.resource_id !== null,
  });
  const circuit = circuits?.circuits.find((item) => item.circuit_id === report.resource_id);

  /** Une écriture de l'assistant touche un domaine quelconque : on rafraîchit large. */
  function refreshEverything(): void {
    void client.invalidateQueries();
  }

  const undo = useMutation({
    mutationFn: (ref: UndoRef) => assistantApi.undo(ref),
    onSuccess: () => {
      setSettled('undone');
      refreshEverything();
      notify('Annulé.', 'signal');
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Annulation impossible.', 'recover');
    },
  });

  const confirm = useMutation({
    mutationFn: () => assistantApi.confirmAction(report.name, report.args),
    onSuccess: (result) => {
      if (result.status !== 'done') {
        notify(result.summary, 'recover');
        return;
      }
      setSettled('confirmed');
      refreshEverything();
      notify(result.summary, 'effort');
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Impossible.', 'recover');
    },
  });

  if (settled === 'dismissed') return null;

  const tone =
    report.status === 'refused' ? 'recover' : report.status === 'pending' ? 'load' : 'effort';

  return (
    <div className={cx(styles.action, styles[`action_${tone}`])}>
      <div className={styles.actionBody}>
        <span className={styles.actionMark} aria-hidden="true" />
        <p className={styles.actionText}>
          {settled === 'undone' ? 'Annulé.' : settled === 'confirmed' ? 'Fait.' : report.summary}
        </p>
      </div>

      {/* Le lien arrive **fabriqué par le serveur** et se rend en bouton, jamais recopié
          dans le texte de la réponse. Une adresse tapée par un modèle est du texte non
          vérifié : le suffixe qui distingue quinze répétitions de quinze secondes s'y perd
          en silence, et la séance se lance quand même — fausse.

          Il vient **avant** « Annuler », et c'est le point de l'écran : ce qu'on veut faire
          d'une séance qu'on vient de recevoir, c'est l'ouvrir. La défaire est le geste
          rare, et il reste à un appui. */}
      {settled === null && report.link !== null && (
        <ExternalLinkButton
          variant="primary"
          className={styles.actionOpen}
          href={report.link}
          aria-label="Ouvrir cette séance dans Cadence"
        >
          Ouvrir dans Cadence
        </ExternalLinkButton>
      )}

      {/* « Fait » juste à côté du lien : après la séance, on revient dans le fil et on la
          consigne sans changer d'écran. La durée est **proposée** par l'estimation et se
          corrige avant de partir — le même geste et les mêmes mots qu'à
          `/activite/seances`, pas un second vocabulaire pour le même acte.

          Le circuit est retrouvé par son identifiant **stable**, jamais par la position
          qu'il occupait au moment de la réponse : elle a pu se décaler depuis. */}
      {/* La carte de séance est celle de `/activite/seances` — **la seule
          implémentation**. Trois copies auraient donné trois façons de dire « Fait »,
          trois arrondis de durée, et le jour où l'une change les deux autres mentent.

          L'import traverse `routes/` : c'est inhabituel, et c'est le moindre mal. La
          séance appartient au domaine Activité ; ce qui est partagé ici, c'est un geste
          métier, pas une primitive d'interface. */}
      {settled === null && circuit !== undefined && (
        <div className={styles.actionCircuit}>
          <CircuitCard circuit={circuit} />
        </div>
      )}

      {settled === null && report.status === 'done' && report.undo !== null && (
        <Button
          variant="quiet"
          busy={undo.isPending}
          onClick={() => {
            undo.mutate(report.undo as UndoRef);
          }}
        >
          Annuler
        </Button>
      )}

      {settled === null && report.status === 'pending' && (
        <div className={styles.actionChoice}>
          <Button
            variant="primary"
            busy={confirm.isPending}
            onClick={() => {
              confirm.mutate();
            }}
          >
            Confirmer
          </Button>
          <Button
            variant="quiet"
            onClick={() => {
              setSettled('dismissed');
            }}
          >
            Non
          </Button>
        </div>
      )}
    </div>
  );
}

// ── Ce qui vient d'être retenu (`IA-10`) ──────────────

/**
 * Le carnet se remplit **tout seul**, et cette ligne annonce ce qu'il vient d'y écrire.
 *
 * L'écran demandait « à retenir ? » et attendait un appui. Ce qui remplace cette
 * validation est le geste inverse — la note est déjà écrite, on la retire si elle est
 * fausse. Une ligne discrète et non un bloc : c'est une conséquence de la réponse, pas un
 * second interlocuteur.
 */
function RememberedNote({ note }: { note: MemoryEntry }) {
  const invalidate = useInvalidateMemory();
  const { notify } = useToast();
  const [gone, setGone] = useState(false);

  const forget = useMutation({
    mutationFn: () => assistantApi.forget(note.id, note.token),
    onSuccess: () => {
      setGone(true);
      invalidate();
      notify('Oublié.', 'signal');
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Impossible de retirer.', 'recover');
    },
  });

  if (gone) return null;

  return (
    <p className={styles.kept}>
      <span className={styles.keptMark} aria-hidden="true">
        ↳
      </span>
      <span className={styles.keptText}>
        Je retiens : <strong>{note.note}</strong>
      </span>
      <Button
        variant="quiet"
        busy={forget.isPending}
        aria-label={`Oublier ${note.note}`}
        onClick={() => {
          forget.mutate();
        }}
      >
        Oublier
      </Button>
    </p>
  );
}

// ── Les fils (`IA-13`) ────────────────────────────────

function ThreadSheet({
  open,
  onClose,
  current,
  onOpenThread,
}: {
  open: boolean;
  onClose: () => void;
  current: string | null;
  onOpenThread: (id: string | null) => void;
}) {
  const client = useQueryClient();
  const { notify } = useToast();
  // Deux appuis pour détruire. Cette feuille était la seule surface destructrice du
  // projet à partir d'un appui unique : supprimer une discussion effaçait un fil entier,
  // sans annulation, à côté d'un bouton qui sert à l'ouvrir. Le carnet juste en dessous
  // et le catalogue d'exercices arment déjà de cette façon.
  const [armed, setArmed] = useState<string | null>(null);

  const { data } = useQuery({
    queryKey: keys.assistant.threads(),
    queryFn: assistantApi.threads,
    enabled: open,
  });

  /** Le fil dont on corrige le titre, et le titre en cours de frappe. */
  const [renaming, setRenaming] = useState<string | null>(null);
  const [title, setTitle] = useState('');

  const rename = useMutation({
    mutationFn: ({ id, next }: { id: string; next: string }) => assistantApi.renameThread(id, next),
    onSuccess: () => {
      setRenaming(null);
      setTitle('');
      void client.invalidateQueries({ queryKey: keys.assistant.all() });
      notify('Discussion renommée.', 'signal');
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Renommage impossible.', 'recover');
    },
  });

  const forget = useMutation({
    mutationFn: (id: string) => assistantApi.forgetThread(id),
    onSuccess: (_result, id) => {
      setArmed(null);
      void client.invalidateQueries({ queryKey: keys.assistant.threads() });
      if (id === current) onOpenThread(null);
      notify('Discussion supprimée.', 'signal');
    },
    onError: (caught: unknown) => {
      setArmed(null);
      notify(caught instanceof ApiError ? caught.message : 'Suppression impossible.', 'recover');
    },
  });

  const threads = data?.threads ?? [];

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Tes discussions"
      lede="Tout est gardé. Rien ne s’efface tout seul."
    >
      <SheetRow
        label="Nouvelle discussion"
        hint="+"
        onClick={() => {
          onOpenThread(null);
          onClose();
        }}
      />

      {threads.length === 0 ? (
        <p className={styles.hint}>Aucune discussion pour l’instant.</p>
      ) : (
        <SheetGroup title="Précédentes">
          {threads.map((thread) => (
            <div key={thread.thread_id} className={styles.threadRow}>
              {/* Ouvrir prend toute la largeur : c'est ce qu'on vient faire neuf fois sur
                  dix. « Supprimer » tenait à côté sur la même ligne et lui prenait une
                  centaine de pixels — à 360 px, un titre de discussion s'y réduisait à
                  deux mots suivis de points de suspension. */}
              {renaming === thread.thread_id ? (
                <form
                  className={styles.renameForm}
                  onSubmit={(event) => {
                    event.preventDefault();
                    rename.mutate({ id: thread.thread_id, next: title });
                  }}
                >
                  <Field
                    label="Titre de la discussion"
                    value={title}
                    autoFocus
                    onChange={(event) => {
                      setTitle(event.target.value);
                    }}
                  />
                  <div className="row">
                    <Button
                      type="submit"
                      variant="primary"
                      busy={rename.isPending}
                      disabled={title.trim() === ''}
                    >
                      Enregistrer
                    </Button>
                    <Button
                      variant="quiet"
                      onClick={() => {
                        setRenaming(null);
                        setTitle('');
                      }}
                    >
                      Annuler
                    </Button>
                  </div>
                </form>
              ) : (
                <SheetRow
                  label={thread.title}
                  hint={`${String(thread.messages)} message${thread.messages > 1 ? 's' : ''}`}
                  onClick={() => {
                    onOpenThread(thread.thread_id);
                    onClose();
                  }}
                />
              )}
              {renaming !== thread.thread_id && (
                <div className={styles.threadActions}>
                  {/* Le modèle nomme le fil à son ouverture, et il se trompe : « Où j'en
                    suis » pour une discussion qui a fini par porter sur une blessure.
                    Sans ce geste, la seule issue était de supprimer le fil — donc la
                    conversation avec son mauvais titre. */}
                  <Chip
                    aria-label={`Renommer « ${thread.title} »`}
                    onClick={() => {
                      setRenaming(thread.thread_id);
                      setTitle(thread.title);
                    }}
                  >
                    Renommer
                  </Chip>
                  <Chip
                    className={cx(armed === thread.thread_id && styles.armed)}
                    disabled={forget.isPending}
                    aria-label={
                      armed === thread.thread_id
                        ? `Supprimer « ${thread.title} » — confirmer`
                        : `Supprimer « ${thread.title} »`
                    }
                    onClick={() => {
                      if (armed !== thread.thread_id) {
                        setArmed(thread.thread_id);
                        return;
                      }
                      forget.mutate(thread.thread_id);
                    }}
                  >
                    {armed === thread.thread_id ? 'Confirmer ?' : 'Supprimer'}
                  </Chip>
                </div>
              )}
            </div>
          ))}
        </SheetGroup>
      )}
    </Sheet>
  );
}

// ── Le carnet (`IA-11`) ───────────────────────────────

/**
 * Le carnet, dans une feuille.
 *
 * Il occupait le bas de l'écran, sous le fil : deux formulaires et une liste qu'il fallait
 * dépasser pour revenir à la question. Il se lit et s'écrit **sans clé API** — c'est
 * `IA-07` pris au mot, et la feuille ne change rien à cela.
 */
function MemorySheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const invalidate = useInvalidateMemory();
  const { notify } = useToast();

  const { data } = useQuery({
    queryKey: keys.assistant.memory(),
    queryFn: assistantApi.memory,
    enabled: open,
  });

  const [topic, setTopic] = useState('autre');
  const [note, setNote] = useState('');
  const [editing, setEditing] = useState<MemoryEntry | null>(null);
  const [armed, setArmed] = useState<number | null>(null);

  const save = useMutation({
    mutationFn: () =>
      editing
        ? assistantApi.update(editing.id, editing.token, topic, note)
        : assistantApi.remember(topic, note),
    onSuccess: () => {
      setNote('');
      setEditing(null);
      setTopic('autre');
      invalidate();
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Enregistrement impossible.', 'recover');
    },
  });

  const forget = useMutation({
    mutationFn: (entry: MemoryEntry) => assistantApi.forget(entry.id, entry.token),
    onSuccess: () => {
      setArmed(null);
      invalidate();
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Suppression impossible.', 'recover');
    },
  });

  /**
   * Marque une note comme n'étant plus vraie, ou la réactive.
   *
   * **Ce n'est pas une suppression, donc pas deux appuis.** Le motif « armer puis
   * confirmer » existe parce que le projet n'a aucune annulation ; ici l'inverse est vrai
   * — le même bouton défait ce qu'il vient de faire. Le demander confirmerait un geste
   * réversible, et finirait par faire ignorer la confirmation là où elle compte.
   *
   * La date vient du serveur. Un écran ne date aucune donnée.
   */
  const resolve = useMutation({
    mutationFn: (entry: MemoryEntry) =>
      assistantApi.update(entry.id, entry.token, entry.topic, entry.note, entry.resolved === null),
    onSuccess: invalidate,
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Changement impossible.', 'recover');
    },
  });

  const entries = data?.memories ?? [];

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Ce que l’assistant sait de toi"
      lede="Ce carnet part avec chaque question. Jamais un chiffre — il serait faux le mois suivant."
    >
      {entries.length === 0 ? (
        <Empty title="Carnet vide">
          Note ce qui explique tes chiffres sans y figurer. L’assistant en retient aussi tout seul
          au fil des questions — tu peux corriger ou oublier ce qu’il garde.
        </Empty>
      ) : (
        <ul className={styles.list}>
          {entries.map((entry) => (
            <li key={entry.memory_id} className={styles.item}>
              <div className={styles.itemBody}>
                <div className={styles.meta}>
                  <span>{entry.topic}</span>
                  {entry.source === 'ai' && <Badge tone="signal">retenue seule</Badge>}
                  {/* Une note résolue reste au carnet, et le dit. La retirer perdrait ce
                      qu'elle apprend — ce qui a déjà lâché est ce qu'un coach surveille. */}
                  {entry.resolved !== null && (
                    <Badge tone="load">résolu le {shortDate(`${entry.resolved}T12:00:00`)}</Badge>
                  )}
                  {entry.created !== null && <span>{shortDate(`${entry.created}T12:00:00`)}</span>}
                </div>
                <span>{entry.note}</span>
              </div>

              <div className={styles.itemActions}>
                {/* Le nom accessible désigne **quelle** note : deux « Corriger » nus ne se
                    distinguent pas à la synthèse vocale, et le carnet en porte autant que
                    de lignes. Même règle que le bouton d'oubli juste à côté. */}
                <Button
                  variant="quiet"
                  aria-label={`Corriger ${entry.note}`}
                  onClick={() => {
                    setEditing(entry);
                    setTopic(entry.topic);
                    setNote(entry.note);
                  }}
                >
                  Corriger
                </Button>
                <Button
                  variant="quiet"
                  busy={resolve.isPending}
                  aria-label={
                    entry.resolved === null
                      ? `Marquer résolu : ${entry.note}`
                      : `Réactiver : ${entry.note}`
                  }
                  onClick={() => {
                    resolve.mutate(entry);
                  }}
                >
                  {entry.resolved === null ? 'Résolu' : 'Réactiver'}
                </Button>
                {/* Deux appuis pour détruire : le projet n'a pas d'annulation. */}
                <Button
                  variant="quiet"
                  busy={forget.isPending}
                  aria-label={
                    armed === entry.id
                      ? `Oublier ${entry.note} — confirmer`
                      : `Oublier ${entry.note}`
                  }
                  onClick={() => {
                    if (armed !== entry.id) {
                      setArmed(entry.id);
                      return;
                    }
                    forget.mutate(entry);
                  }}
                >
                  {armed === entry.id ? 'Confirmer ?' : 'Oublier'}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <SheetGroup title={editing ? 'Corriger la note' : 'Noter quelque chose'}>
        <form
          className={styles.memoryForm}
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate();
          }}
        >
          <ChipStrip label="Sujet">
            {(data?.topics ?? []).map((option) => (
              <Chip
                key={option}
                selected={topic === option}
                onClick={() => {
                  setTopic(option);
                }}
              >
                {option}
              </Chip>
            ))}
          </ChipStrip>

          <Field
            label="La note"
            value={note}
            placeholder="Genou droit sensible depuis le 12 juillet"
            hint="Ce qu’aucun fichier ne porte, et qui vaudra encore dans six mois."
            onChange={(event) => {
              setNote(event.target.value);
            }}
          />

          <div className="row">
            <Button
              type="submit"
              variant="primary"
              busy={save.isPending}
              disabled={note.trim() === ''}
            >
              {editing ? 'Enregistrer' : 'Noter'}
            </Button>
            {editing && (
              <Button
                variant="quiet"
                onClick={() => {
                  setEditing(null);
                  setNote('');
                  setTopic('autre');
                }}
              >
                Annuler
              </Button>
            )}
          </div>
        </form>
      </SheetGroup>
    </Sheet>
  );
}

// ── Écran ─────────────────────────────────────────────

export function Assistant() {
  const { enabled, pending: statusPending, message } = useAiStatus();
  // Tant qu'on ne sait pas, on laisse écrire. Déclarer l'assistance indisponible avant
  // d'avoir posé la question afficherait un écran d'échec à chaque ouverture.
  const usable = enabled || statusPending;
  const { notify } = useToast();

  const [question, setQuestion] = useState('');
  /**
   * La question en vol, affichée avant même la réponse.
   *
   * Deux raisons, et la seconde est un correctif. D'abord le confort : dans une
   * messagerie, ce qu'on envoie apparaît **tout de suite** — attendre la réponse pour
   * afficher sa propre phrase donne l'impression d'un envoi qui n'est pas parti.
   *
   * Ensuite la fiabilité de l'attente. Les trois points étaient pilotés par `isPending` de
   * la mutation, et ils restaient affichés après l'arrivée de la réponse. Ici l'état est
   * à nous, et il est remis à zéro dans `onSettled` — donc au succès **comme** à l'échec,
   * ce qu'un `onSuccess` seul ne garantit pas.
   */
  const [inFlight, setInFlight] = useState<string | null>(null);
  /** Les tours de **cette session**. Le passé du fil est dérivé, pas recopié. */
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  /** La réponse qu'on vient de copier, pour le dire sur son propre bouton. */
  const [copied, setCopied] = useState<string | null>(null);
  /**
   * Ce que le serveur est en train de faire, dit par lui.
   *
   * **Il n'est pas deviné ici.** Une suite d'étapes affichée sur une minuterie serait une
   * valeur inventée à l'écran, exactement comme un chiffre : elle décrirait un travail
   * dont le client ne sait rien. Chaque étape arrive du flux au moment où elle commence.
   */
  const [step, setStep] = useState<string | null>(null);
  /**
   * La réponse pendant qu'elle s'écrit.
   *
   * **Ce n'est pas une cinquième façon de dire « proposé ».** C'est le même `reply`, qui
   * arrive plus tôt — le serveur ne diffuse que ce qu'il a prouvé final, et le texte
   * affiché ici est mot pour mot celui que `onSuccess` posera dans le fil. Rien à
   * rattraper, rien à effacer, donc rien à signaler à l'utilisateur.
   *
   * Remis à zéro par `onSettled` comme `step`, et par `event: reset` quand un modèle
   * tombe après avoir parlé — le seul cas où le début affiché n'aura pas de suite.
   */
  const [draft, setDraft] = useState('');
  /**
   * Les deux feuilles s'ouvrent **par l'adresse** — `?ouvre=memoire` — et un fil s'ouvre
   * de même — `?fil=<identifiant>`.
   *
   * Le tableau de bord y mène directement, et une surface qu'on atteint depuis un autre
   * écran a besoin d'être adressable : sans cela, le lien ouvrirait la conversation et
   * l'utilisateur aurait un appui de plus à faire, sans savoir lequel.
   *
   * **`?fil` est ce qui fait tenir la lecture du jour.** La carte d'accueil ouvre un fil
   * dont le premier message est celui de l'assistant, et l'écran doit arriver *dedans* :
   * poser le texte dans le champ de saisie ferait répondre le modèle à une phrase qu'il
   * ne se souviendrait pas d'avoir écrite, puisque `_history` ne la porterait pas.
   *
   * `?ouvre` est **retiré à la fermeture** : sans quoi le bouton système « précédent »
   * rouvrirait la feuille qu'on vient de refermer, ce qui est le piège classique d'un
   * état d'interface porté par l'URL.
   *
   * `?fil` reste, lui, **tant qu'on est dans ce fil-là** : ce n'est pas un état
   * d'interface mais une adresse, et recharger la page doit ramener où l'on était. Il
   * n'est retiré qu'en ouvrant un autre fil, moment où il annoncerait autre chose que ce
   * qu'on lit. `replace` évite d'ajouter une entrée d'historique dans les deux cas.
   */
  const [params, setParams] = useSearchParams();
  const asked = params.get('ouvre');
  const [chosen, setChosen] = useState<string | null>(params.get('fil'));
  /**
   * Vrai dès que l'utilisateur a **pris la main** sur le fil : ouvert celui-ci, fermé
   * celui-là, ou posé une question. Tant que c'est faux, la reprise automatique peut
   * décider ; après, elle se tait — un rattrapage qui rouvrirait un fil qu'on vient de
   * fermer serait une porte qui se rouvre toute seule.
   *
   * Un `?fil` dans l'adresse compte comme un choix : c'est une adresse, pas un défaut.
   */
  const [decided, setDecided] = useState(params.has('fil'));

  function openThread(id: string | null): void {
    setDecided(true);
    setChosen(id);
  }
  const [threadsOpen, setThreadsOpen] = useState(asked === 'discussions');
  const [memoryOpen, setMemoryOpen] = useState(asked === 'memoire');

  function forget(): void {
    if (!params.has('ouvre') && !params.has('fil')) return;
    const next = new URLSearchParams(params);
    next.delete('ouvre');
    next.delete('fil');
    setParams(next, { replace: true });
  }

  const stream = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  /**
   * Le fil suit-il le bas ?
   *
   * Une référence et non un état : elle change à chaque pixel de défilement, et en faire
   * un état redessinerait la conversation entière pendant qu'on la relit.
   */
  const following = useRef(true);

  /**
   * Reprendre la conversation en cours, quand il y en a une.
   *
   * Ouvrir l'assistant deux minutes après l'avoir fermé et retomber sur une page vide,
   * c'est perdre le contexte de ce qu'on était en train de faire — et devoir le réexpliquer
   * au modèle. Au-delà d'une heure, on revient pour autre chose, et rouvrir donnerait au
   * modèle un passé qui ne parle plus de rien.
   *
   * **C'est le serveur qui tranche.** Il rend un identifiant ou rien ; l'écran n'a aucun
   * écart de temps à mesurer, ce qui serait un second calcul de date (`HEAT-32`).
   *
   * Ne s'applique **qu'au montage et sur un écran vierge** : ni sur un `?fil` explicite —
   * qui est une adresse —, ni après avoir fermé un fil à la main, geste qu'un rattrapage
   * automatique annulerait sous le doigt.
   */
  const resume = useQuery({
    queryKey: keys.assistant.threads(),
    queryFn: assistantApi.threads,
  });

  /**
   * Le fil réellement ouvert — **dérivé au rendu**, pas posé par un effet.
   *
   * Un `useEffect` qui appellerait `setThreadId` provoquerait un rendu en cascade pour une
   * valeur qu'on sait déjà calculer ici. La reprise n'est qu'un défaut : elle s'applique
   * tant que rien n'a été choisi, et le choix l'emporte dès qu'il existe.
   */
  const threadId = chosen ?? (decided ? null : (resume.data?.resume ?? null));

  const opened = useQuery({
    queryKey: keys.assistant.thread(threadId ?? ''),
    queryFn: () => assistantApi.thread(threadId ?? ''),
    enabled: threadId !== null && exchanges.length === 0,
  });

  /** Le passé du fil, **dérivé** de ce que le serveur rend — jamais recopié dans un état. */
  const past = useMemo((): Exchange[] => {
    const messages = opened.data?.messages ?? [];
    const rebuilt: Exchange[] = [];
    for (let index = 0; index < messages.length; index += 1) {
      const turn = messages[index];
      if (turn?.role !== 'user') continue;
      const answer = messages[index + 1];
      rebuilt.push({
        question: turn.content,
        reply: answer?.role === 'assistant' ? answer.content : '',
        // **Les actions sont rejouées**, moins leur annulation — que le serveur ne range
        // pas, justement parce que le jeton d'une ligne périme dès qu'elle change. Ce qui
        // reste ne périme pas : un lien Cadence porte la séance entière, et retrouver la
        // séance qu'on s'est fait proposer est précisément ce qu'on vient chercher en
        // rouvrant un fil.
        actions: answer?.role === 'assistant' ? (answer.actions ?? []) : [],
        remembered: [],
        context: answer?.role === 'assistant' ? (answer.context ?? []) : [],
      });
    }
    return rebuilt;
  }, [opened.data]);

  // Chronologique : le plus ancien en haut, le dernier en bas, comme une conversation.
  const shown = [...past, ...exchanges];

  const ask = useMutation({
    mutationFn: (asked: string) =>
      assistantApi.askStreaming(
        asked,
        threadId,
        setStep,
        (text) => {
          setDraft((current) => current + text);
        },
        () => {
          setDraft('');
        },
      ),
    onSuccess: (result, asked) => {
      openThread(result.thread_id);
      setExchanges((current) => [
        ...current.filter((turn) => turn.question !== asked || turn.failure === undefined),
        {
          question: asked,
          reply: result.reply,
          actions: result.actions,
          remembered: result.remember,
          context: result.context,
        },
      ]);
      following.current = true;
    },
    onError: (caught: unknown, asked) => {
      const why = caught instanceof ApiError ? caught.message : 'Question impossible.';
      notify(why, 'recover');
      /*
       * **L'échec reste dans le fil, avec sa question.**
       *
       * Elle revenait dans le champ de saisie : il fallait la renvoyer à la main, et si
       * l'on avait commencé à taper autre chose entre-temps, elle était simplement
       * perdue. Ici elle garde sa place dans la conversation, à l'endroit où elle a
       * échoué, et un bouton la rejoue.
       */
      setExchanges((current) => [
        ...current.filter((turn) => turn.question !== asked || turn.failure === undefined),
        { question: asked, reply: '', actions: [], remembered: [], context: [], failure: why },
      ]);
      following.current = true;
    },
    onSettled: () => {
      setInFlight(null);
      setStep(null);
      setDraft('');
    },
  });

  /**
   * La saisie grandit avec ce qu'on y écrit, jusqu'à un plafond.
   *
   * Elle était figée à `rows={1}` : coller ses notes de séance — six exercices — revenait
   * à les taper dans une fente d'une ligne, sans jamais voir plus d'une phrase de ce
   * qu'on venait d'écrire. C'est le champ que C07 remplira le plus.
   *
   * Le plafond est en CSS (`max-height`) et non ici : au-delà, le champ défile de
   * lui-même. Sans lui, une note de quinze lignes mangerait la conversation entière.
   *
   * Remettre `height` à `auto` avant de lire `scrollHeight` n'est pas une précaution :
   * sans cela, la hauteur ne redescend jamais quand on efface.
   */
  useEffect(() => {
    const node = composer.current;
    if (node === null) return;
    node.style.height = 'auto';
    node.style.height = `${String(node.scrollHeight)}px`;
  }, [question]);

  /**
   * Le fil se pose en bas à l'arrivée d'un message — **sauf si on est remonté**.
   *
   * Sans cette garde, relire une réponse d'il y a dix questions se ferait arracher dès que
   * la suivante arrive. C'est le défaut le plus courant des interfaces de discussion, et
   * il ne coûte qu'une référence à éviter.
   *
   * **`draft` est dans les dépendances, et il a fallu y penser.** Le nombre de messages ne
   * bouge pas pendant qu'une réponse se diffuse : sans lui, une réponse longue grandirait
   * sous le bas de l'écran et on la regarderait partir. Le lot qui allonge les réponses
   * est exactement celui qui rend cette dépendance nécessaire.
   */
  useEffect(() => {
    if (!following.current) return;
    const node = stream.current;
    if (node !== null) node.scrollTop = node.scrollHeight;
  }, [shown.length, inFlight, draft]);

  function send(): void {
    const cleaned = question.trim();
    if (cleaned === '' || inFlight !== null) return;
    setInFlight(cleaned);
    setQuestion('');
    following.current = true;
    ask.mutate(cleaned);
  }

  /** Rejoue une question échouée, en retirant le tour raté de la conversation. */
  function retry(asked: string, position: number): void {
    if (inFlight !== null) return;
    setExchanges((current) => current.filter((_turn, index) => index + past.length !== position));
    setInFlight(asked);
    following.current = true;
    ask.mutate(asked);
  }

  /**
   * Copie une réponse, et le dit.
   *
   * Un retour d'état plutôt qu'un toast : le geste est local à une bulle, et un bandeau
   * en bas de l'écran pour dire « copié » demande de regarder ailleurs que là où l'on
   * vient d'appuyer.
   */
  function copy(text: string): void {
    void navigator.clipboard
      .writeText(text)
      .then(() => {
        setCopied(text);
        window.setTimeout(() => {
          setCopied((current) => (current === text ? null : current));
        }, 2000);
      })
      .catch(() => {
        notify('Copie impossible sur cet appareil.', 'recover');
      });
  }

  return (
    <div className={styles.screen}>
      <header className={styles.bar}>
        {/* Le titre du fil, et non « Assistant » : l'onglet du bas le dit déjà, et ce
            qu'on cherche ici est de quelle discussion il s'agit. */}
        <h2 className={styles.title}>{opened.data?.title ?? 'Nouvelle discussion'}</h2>
        {/* Deux icônes et non deux libellés : « Mémoire » et « Discussions » prenaient
            plus de la moitié de la barre, et le titre du fil — la seule chose qui change
            d'un écran à l'autre — s'y retrouvait tronqué à « Nouvelle discu… ». */}
        <div className={styles.barActions}>
          <Button
            variant="quiet"
            className={styles.iconButton}
            aria-label="Mémoire"
            aria-haspopup="dialog"
            aria-expanded={memoryOpen}
            onClick={() => {
              setMemoryOpen(true);
            }}
          >
            <IconBook size={20} />
          </Button>
          <Button
            variant="ghost"
            className={styles.iconButton}
            aria-label="Discussions"
            aria-haspopup="dialog"
            aria-expanded={threadsOpen}
            onClick={() => {
              setThreadsOpen(true);
            }}
          >
            <IconThreads size={20} />
          </Button>
        </div>
      </header>

      <div
        className={styles.stream}
        ref={stream}
        onScroll={(event) => {
          const node = event.currentTarget;
          // 40 px de marge : on « suit » encore si on est presque en bas, sinon un demi-
          // pixel d'inertie suffirait à décrocher le fil.
          following.current = node.scrollHeight - node.scrollTop - node.clientHeight < 40;
        }}
      >
        {!usable && (
          <Empty title="Assistance indisponible">
            {message}
            <br />
            Le carnet, lui, reste utilisable : il se lit et s’écrit à la main.
          </Empty>
        )}

        {/* L'état vide reste **un** état sur quatre : il ne peut pas disparaître, sinon
            un fil neuf serait un écran blanc sans rien qui dise quoi faire. Mais il tient
            en une ligne — le paragraphe qui décrivait ce que l'assistant lit et les quatre
            questions toutes faites sont partis avec le reste. */}
        {/* `inFlight` compte comme un tour : sans lui, « le fil commence ici » restait
            affiché **au-dessus de la question qu'on vient d'envoyer**. L'état vide
            décrivait alors un écran que l'utilisateur n'avait plus sous les yeux. */}
        {usable && shown.length === 0 && inFlight === null && (
          <p className={styles.welcomeText}>Pose ta question : le fil commence ici.</p>
        )}

        {shown.map((turn, index) => (
          <div className={styles.turn} key={`${String(index)}-${turn.question.slice(0, 24)}`}>
            <p className={cx(styles.bubble, styles.mine)}>{turn.question}</p>

            {turn.reply !== '' && (
              <div className={cx(styles.bubble, styles.theirs)}>
                {/* Le modèle écrit du markdown ; il s'affichait en clair, ses `-` et ses
                    `**` compris. Rendu en nœuds React, jamais en HTML injecté. */}
                <Markdown>{turn.reply}</Markdown>
              </div>
            )}

            {turn.reply !== '' && (
              <div className={styles.replyActions}>
                {/* Une pastille et non un bouton discret : sans bordure, « Copier » se
                    lisait comme une légende posée sous la bulle, et rien ne disait qu'on
                    pouvait appuyer dessus. C'est le vocabulaire des actions de ligne du
                    reste de l'application, et il a déjà été choisi pour cette raison. */}
                <Chip
                  aria-label="Copier la réponse"
                  onClick={() => {
                    copy(turn.reply);
                  }}
                >
                  {copied === turn.reply ? 'Copié' : 'Copier'}
                </Chip>
              </div>
            )}

            {/* Un tour qui a échoué garde sa question et propose de la rejouer. Elle
                revenait dans le champ, ce qui obligeait à la renvoyer à la main — et à
                la retrouver si l'on avait déjà tapé autre chose. */}
            {turn.failure !== undefined && (
              <div className={styles.failure} role="alert">
                <span>{turn.failure}</span>
                <Button
                  variant="ghost"
                  disabled={inFlight !== null}
                  onClick={() => {
                    retry(turn.question, index);
                  }}
                >
                  Réessayer
                </Button>
              </div>
            )}

            {turn.actions.map((report, position) => (
              <ActionCard key={`${report.name}-${String(position)}`} report={report} />
            ))}

            {turn.remembered.map((note) => (
              <RememberedNote key={note.memory_id} note={note} />
            ))}

            {/* Le condensé accompagne **la** réponse qu'il a produite, et lui seule. Il
                est porté par le tour désormais, et non par l'écran : il restait sinon
                collé au dernier échange et disparaissait au suivant, alors que c'est
                justement en relisant une vieille réponse qu'on veut savoir sur quoi elle
                s'appuyait. `IA-09` rendu vérifiable plutôt que déclaratif. */}
            {turn.context.length > 0 && (
              <details className={styles.facts}>
                <summary>
                  Ce qui a été envoyé ({turn.context.length} {plural(turn.context.length, 'ligne')},
                  aucun fichier)
                </summary>
                <ul>
                  {turn.context.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        ))}

        {inFlight !== null && (
          <div className={styles.turn}>
            <p className={cx(styles.bubble, styles.mine)}>{inFlight}</p>
            {/* Trois états, et non deux, parce que l'attente en a trois.
                Le texte dès qu'il arrive ; à défaut l'étape en cours, qui vient du
                serveur ; à défaut les trois points. La durée varie du simple au triple
                selon qu'une seconde passe est nécessaire, et rien de tout cela ne se
                devine côté écran. */}
            <p
              className={cx(
                styles.bubble,
                styles.theirs,
                draft === '' && step === null && styles.thinking,
              )}
              aria-label={draft === '' ? 'L’assistant réfléchit' : undefined}
              aria-live="polite"
            >
              {draft !== '' ? (
                draft
              ) : step !== null ? (
                <span className={styles.step}>{step}…</span>
              ) : (
                <>
                  <span />
                  <span />
                  <span />
                </>
              )}
            </p>
          </div>
        )}
      </div>

      <form
        className={styles.composer}
        onSubmit={(event) => {
          event.preventDefault();
          send();
        }}
      >
        <label className="sr-only" htmlFor="question">
          Ta question
        </label>
        <textarea
          id="question"
          className={styles.input}
          ref={composer}
          rows={1}
          value={question}
          placeholder={usable ? 'Écris ta question…' : 'Assistance indisponible'}
          disabled={!usable}
          onChange={(event) => {
            setQuestion(event.target.value);
          }}
          onKeyDown={(event) => {
            // Entrée envoie, Maj+Entrée passe à la ligne — la convention de toutes les
            // messageries. `isComposing` protège les claviers à composition (accents,
            // idéogrammes) : sans lui, valider un caractère enverrait le message.
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              send();
            }
          }}
        />
        <Button
          type="submit"
          variant="primary"
          className={styles.send}
          busy={inFlight !== null}
          disabled={question.trim() === '' || !usable}
          aria-label="Envoyer"
        >
          ↑
        </Button>
      </form>

      <ThreadSheet
        open={threadsOpen}
        current={threadId}
        onClose={() => {
          setThreadsOpen(false);
          forget();
        }}
        onOpenThread={(id) => {
          openThread(id);
          setExchanges([]);
          following.current = true;
          // L'adresse cesse d'annoncer le fil qu'on vient de quitter.
          forget();
        }}
      />

      <MemorySheet
        open={memoryOpen}
        onClose={() => {
          setMemoryOpen(false);
          forget();
        }}
      />
    </div>
  );
}
