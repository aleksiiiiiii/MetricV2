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

import {
  Badge,
  Button,
  Chip,
  ChipStrip,
  Empty,
  Field,
  Sheet,
  SheetGroup,
  SheetRow,
} from '@/components/ui';
import { IconBook, IconThreads } from '@/components/ui/icons';
import { useAiStatus } from '@/features/ai/useAiStatus';
import {
  assistantApi,
  type ActionReport,
  type MemoryEntry,
  type UndoRef,
} from '@/features/assistant/api';
import { ApiError } from '@/lib/api';
import { cx } from '@/lib/cx';
import { shortDate } from '@/lib/format';
import { keys } from '@/lib/query';
import { useToast } from '@/lib/toast';

import styles from './Assistant.module.css';

/** Questions offertes en un appui, pour que l'écran vide ne soit pas un champ nu. */
const EXAMPLES = [
  'Où j’en suis cette semaine ?',
  'Pourquoi je stagne ?',
  'Qu’est-ce que je néglige ?',
  'Note ma séance de ce matin',
];

/** Une question, sa réponse, et ce que l'assistant a fait à ce tour-là. */
interface Exchange {
  question: string;
  reply: string;
  actions: ActionReport[];
  remembered: MemoryEntry[];
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

  const { data } = useQuery({
    queryKey: keys.assistant.threads(),
    queryFn: assistantApi.threads,
    enabled: open,
  });

  const forget = useMutation({
    mutationFn: (id: string) => assistantApi.forgetThread(id),
    onSuccess: (_result, id) => {
      void client.invalidateQueries({ queryKey: keys.assistant.threads() });
      if (id === current) onOpenThread(null);
      notify('Discussion supprimée.', 'signal');
    },
    onError: (caught: unknown) => {
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
              <SheetRow
                label={thread.title}
                hint={`${String(thread.messages)} message${thread.messages > 1 ? 's' : ''}`}
                onClick={() => {
                  onOpenThread(thread.thread_id);
                  onClose();
                }}
              />
              <Button
                variant="quiet"
                aria-label={`Supprimer « ${thread.title} »`}
                busy={forget.isPending}
                onClick={() => {
                  forget.mutate(thread.thread_id);
                }}
              >
                Supprimer
              </Button>
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
  const [context, setContext] = useState<string[]>([]);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [threadsOpen, setThreadsOpen] = useState(false);
  const [memoryOpen, setMemoryOpen] = useState(false);

  const stream = useRef<HTMLDivElement>(null);
  /**
   * Le fil suit-il le bas ?
   *
   * Une référence et non un état : elle change à chaque pixel de défilement, et en faire
   * un état redessinerait la conversation entière pendant qu'on la relit.
   */
  const following = useRef(true);

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
        // Les actions ne sont pas rejouées : l'annulation d'un ajout a expiré avec le
        // jeton de sa ligne, et proposer un geste qui échouerait serait pire que de ne
        // rien proposer.
        actions: [],
        remembered: [],
      });
    }
    return rebuilt;
  }, [opened.data]);

  // Chronologique : le plus ancien en haut, le dernier en bas, comme une conversation.
  const shown = [...past, ...exchanges];

  const ask = useMutation({
    mutationFn: (asked: string) => assistantApi.ask(asked, threadId),
    onSuccess: (result, asked) => {
      setThreadId(result.thread_id);
      setExchanges((current) => [
        ...current,
        {
          question: asked,
          reply: result.reply,
          actions: result.actions,
          remembered: result.remember,
        },
      ]);
      setContext(result.context);
      following.current = true;
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Question impossible.', 'recover');
      // La question revient dans le champ : elle n'est pas perdue avec l'échec.
      setQuestion((current) => (current === '' ? (inFlight ?? '') : current));
    },
    onSettled: () => {
      setInFlight(null);
    },
  });

  /**
   * Le fil se pose en bas à l'arrivée d'un message — **sauf si on est remonté**.
   *
   * Sans cette garde, relire une réponse d'il y a dix questions se ferait arracher dès que
   * la suivante arrive. C'est le défaut le plus courant des interfaces de discussion, et
   * il ne coûte qu'une référence à éviter.
   */
  useEffect(() => {
    if (!following.current) return;
    const node = stream.current;
    if (node !== null) node.scrollTop = node.scrollHeight;
  }, [shown.length, inFlight]);

  function send(): void {
    const cleaned = question.trim();
    if (cleaned === '' || inFlight !== null) return;
    setInFlight(cleaned);
    setQuestion('');
    following.current = true;
    ask.mutate(cleaned);
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

      {/* `IA-12` — permanent, jamais repliable : une mention qu'on ferme est une mention
          qu'on ne lit plus. Elle tient sur deux lignes pour ne pas manger le fil. */}
      <p className={styles.caution}>
        L’assistant n’est pas médecin : aucun diagnostic, aucune interprétation de symptôme. Devant
        une douleur, consulte un professionnel de santé.
      </p>

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

        {usable && shown.length === 0 && (
          <div className={styles.welcome}>
            <p className={styles.welcomeText}>
              L’assistant lit tes chiffres — poids, séances, protéines, hydratation, objectif,
              planning — et ton carnet. Il ne voit aucun de tes fichiers, et il peut noter pour toi.
            </p>
            <div className={styles.examples}>
              {EXAMPLES.map((example) => (
                <Chip
                  key={example}
                  onClick={() => {
                    setQuestion(example);
                  }}
                >
                  {example}
                </Chip>
              ))}
            </div>
          </div>
        )}

        {shown.map((turn, index) => (
          <div className={styles.turn} key={`${String(index)}-${turn.question.slice(0, 24)}`}>
            <p className={cx(styles.bubble, styles.mine)}>{turn.question}</p>

            {turn.reply !== '' && <p className={cx(styles.bubble, styles.theirs)}>{turn.reply}</p>}

            {turn.actions.map((report, position) => (
              <ActionCard key={`${report.name}-${String(position)}`} report={report} />
            ))}

            {turn.remembered.map((note) => (
              <RememberedNote key={note.memory_id} note={note} />
            ))}

            {/* Le condensé accompagne **la** réponse qu'il a produite, et lui seule : il
                est recalculé à chaque question, et l'afficher une fois pour tout le fil
                laisserait croire qu'il valait aussi pour les précédentes. `IA-09` rendu
                vérifiable plutôt que déclaratif. */}
            {index === shown.length - 1 && context.length > 0 && (
              <details className={styles.facts}>
                <summary>Ce qui a été envoyé ({context.length} lignes, aucun fichier)</summary>
                <ul>
                  {context.map((line) => (
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
            <p
              className={cx(styles.bubble, styles.theirs, styles.thinking)}
              aria-label="L’assistant réfléchit"
              aria-live="polite"
            >
              <span />
              <span />
              <span />
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
        }}
        onOpenThread={(id) => {
          setThreadId(id);
          setExchanges([]);
          setContext([]);
          following.current = true;
        }}
      />

      <MemorySheet
        open={memoryOpen}
        onClose={() => {
          setMemoryOpen(false);
        }}
      />
    </div>
  );
}
