import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';

import {
  AiBlock,
  Badge,
  Button,
  Card,
  Chip,
  ChipStrip,
  Empty,
  Field,
  Rule,
  Sheet,
  SheetGroup,
  SheetRow,
} from '@/components/ui';
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

/**
 * Écran Assistant (`L14b-07`).
 *
 * ## Ce que l'écran ne fait pas
 *
 * Il ne construit aucun contexte. Le condensé — les cinq métriques, l'objectif, l'assiduité,
 * le respect du planning, les bilans, le carnet — est assemblé **par le serveur**, à partir
 * des services qui en détiennent chacun la règle. L'écran le reçoit, l'affiche, et ne le
 * réécrit pas.
 *
 * Il ne décide pas non plus de ce qui mérite d'être retenu, ni de ce qui s'écrit dans les
 * données. Le carnet se remplit **côté serveur** pendant la conversation, et les actions
 * sont validées et exécutées là-bas : cet écran reçoit un compte rendu et offre le geste
 * qui va avec — annuler un ajout, confirmer un changement, oublier une note.
 *
 * ## Le fil vit sur le serveur
 *
 * Il n'y vivait pas : cet écran rendait l'historique à chaque question et le perdait au
 * rechargement. Depuis que la conversation peut **écrire**, le passé ne peut plus venir de
 * l'appelant — un client fabriquerait sinon le passé qui justifie l'action qu'il veut voir
 * prendre. L'écran ne rend donc plus qu'un identifiant de fil, et le serveur lit le reste.
 */

/** Questions offertes en un appui, pour que l'écran vide ne soit pas un champ nu. */
const EXAMPLES = [
  'Où j’en suis cette semaine ?',
  'Pourquoi je stagne ?',
  'Qu’est-ce que je néglige ?',
];

/** Une question et sa réponse. C'est l'unité que l'écran affiche, et elle ne se sépare pas. */
interface Exchange {
  question: string;
  reply: string;
  /** Ce que l'assistant a fait ou demande à faire **à ce tour-là**. */
  actions: ActionReport[];
}

function useInvalidateMemory() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: keys.assistant.all() });
  };
}

// ── Le carnet (`IA-10`, `IA-11`) ──────────────────────

function MemoryCard({ entries, topics }: { entries: MemoryEntry[]; topics: string[] }) {
  const invalidate = useInvalidateMemory();
  const { notify } = useToast();

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

  return (
    <Card>
      <h3>Ce que l’assistant sait de toi</h3>
      <p className={styles.note}>
        Ce carnet part avec chaque question. Il porte ce qu’aucun fichier ne dit — une blessure, un
        sommeil, une contrainte — et jamais un chiffre, qui serait faux le mois suivant.
      </p>

      {entries.length === 0 && (
        <Empty title="Carnet vide">
          Note ce qui explique tes chiffres sans y figurer. L’assistant en retient aussi tout seul
          au fil des questions — tu peux corriger ou oublier ce qu’il garde.
        </Empty>
      )}

      {entries.length > 0 && (
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
                {/* Le nom accessible désigne **quelle** note : deux « Corriger » nus
                    ne se distinguent pas à la synthèse vocale, et le carnet en porte
                    autant que de lignes. Même règle que le bouton d'oubli juste à côté. */}
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
                {/* Deux appuis pour détruire : le projet n'a pas d'annulation, et le nom
                    accessible désigne **quelle** note — la même règle que `SwipeRow`. */}
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

      <Rule>{editing ? 'Corriger la note' : 'Noter quelque chose'}</Rule>

      <form
        className={styles.form}
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate();
        }}
      >
        <ChipStrip label="Sujet">
          {topics.map((option) => (
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
            className={styles.submit}
          >
            {/* « Noter » et non « Retenir » : le bloc IA porte déjà un « Retenir », et
                deux boutons de même nom pour deux gestes différents sur un même écran est
                exactement ce que le nom accessible d'une suppression cherche à éviter.
                Défaut trouvé par un test qui ne savait plus lequel viser. */}
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
    </Card>
  );
}

// ── Les fils (`IA-13`) ────────────────────────────────

/**
 * La liste des discussions, dans une feuille.
 *
 * Une feuille et non une page : on y entre pour choisir une ligne et en ressortir, ce qui
 * est exactement ce qu'un `Sheet` fait — il monte sous le pouce, il n'efface pas l'écran
 * qu'on regardait, et il se referme d'un geste vers le bas.
 */
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
        <p className={styles.note}>Aucune discussion pour l’instant.</p>
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
 * Le carnet se remplit **tout seul**, et ce bloc annonce ce qu'il vient d'y écrire.
 *
 * L'écran demandait « à retenir ? » et attendait un appui. Ce qui remplace cette
 * validation est le geste inverse — la note est déjà écrite, et on la retire si elle est
 * fausse. C'est le pendant exact de l'annulation d'un ajout, et le compromis tient parce
 * qu'une note fausse ne casse aucun chiffre : elle change ce que l'assistant croit
 * savoir, et cela se lit.
 */
function Remembered({ notes }: { notes: MemoryEntry[] }) {
  const invalidate = useInvalidateMemory();
  const { notify } = useToast();
  const [removed, setRemoved] = useState<Set<number>>(new Set());

  const forget = useMutation({
    mutationFn: (note: MemoryEntry) => assistantApi.forget(note.id, note.token),
    onSuccess: (_result, note) => {
      setRemoved((current) => new Set(current).add(note.id));
      invalidate();
      notify('Oublié.', 'signal');
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Impossible de retirer.', 'recover');
    },
  });

  const left = notes.filter((note) => !removed.has(note.id));
  if (left.length === 0) return null;

  return (
    <AiBlock tag="Je retiens">
      <ul className={styles.proposed}>
        {left.map((note) => (
          <li key={note.memory_id} className={styles.item}>
            <div className={styles.itemBody}>
              <span className={styles.meta}>{note.topic}</span>
              <strong>{note.note}</strong>
            </div>
            <Button
              variant="quiet"
              busy={forget.isPending}
              aria-label={`Oublier ${note.note}`}
              onClick={() => {
                forget.mutate(note);
              }}
            >
              Oublier
            </Button>
          </li>
        ))}
      </ul>
    </AiBlock>
  );
}

// ── Écran ─────────────────────────────────────────────

export function Assistant() {
  const { enabled, message } = useAiStatus();
  const { notify } = useToast();

  const [question, setQuestion] = useState('');
  /**
   * Les échanges, **du plus récent au plus ancien**.
   *
   * L'ordre n'est pas un goût. Mesuré dans le navigateur, un fil chronologique avec le
   * champ en dessous faisait descendre celui-ci de 289 px par échange : à la troisième
   * question il tombait à 1304 px, très en dessous du pli d'un iPhone. C'est-à-dire que
   * l'écran dont le seul objet est de poser des questions rendait sa question de plus en
   * plus difficile à poser.
   *
   * Le décroissant est par ailleurs la convention de tout le projet — historique
   * d'activité, bilans, carnet — et il place la dernière réponse juste sous le champ.
   */
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [remembered, setRemembered] = useState<MemoryEntry[]>([]);
  const [context, setContext] = useState<string[]>([]);

  const { data, isPending, error } = useQuery({
    queryKey: keys.assistant.memory(),
    queryFn: assistantApi.memory,
  });

  // L'identifiant du fil courant. Le passé n'est plus reconstruit par l'écran : le
  // serveur le lit dans le fil, et l'écran ne lui donne que de quoi le retrouver.
  const [threadId, setThreadId] = useState<string | null>(null);
  const [threadsOpen, setThreadsOpen] = useState(false);

  // Ouvrir un fil ancien le rejoue dans l'écran. Le serveur le détient : l'écran ne
  // reconstruit rien, il affiche ce qu'on lui rend.
  const opened = useQuery({
    queryKey: keys.assistant.thread(threadId ?? ''),
    queryFn: () => assistantApi.thread(threadId ?? ''),
    enabled: threadId !== null && exchanges.length === 0,
  });

  /**
   * Le passé du fil, **dérivé** de ce que le serveur rend — jamais recopié dans un état.
   *
   * Le recopier dans un effet marchait, et c'était fragile : deux sources pour la même
   * liste, qu'il fallait garder d'accord à chaque ouverture, chaque question et chaque
   * suppression. Ici il n'y en a qu'une, et `exchanges` ne porte plus que les tours de
   * cette session-ci.
   */
  const past = useMemo((): Exchange[] => {
    const messages = opened.data?.messages ?? [];
    const rebuilt: Exchange[] = [];
    for (let index = 0; index < messages.length; index += 1) {
      const turn = messages[index];
      if (turn?.role !== 'user') continue;
      const answer = messages[index + 1];
      rebuilt.unshift({
        question: turn.content,
        reply: answer?.role === 'assistant' ? answer.content : '',
        // Les actions ne sont pas rejouées : l'annulation d'un ajout a expiré avec le
        // jeton de sa ligne, et proposer un geste qui échouerait serait pire que de ne
        // rien proposer.
        actions: [],
      });
    }
    return rebuilt;
  }, [opened.data]);

  // Les tours de cette session d'abord — ils sont les plus récents.
  const shown = [...exchanges, ...past];

  const ask = useMutation({
    mutationFn: (asked: string) => assistantApi.ask(asked, threadId),
    onSuccess: (result, asked) => {
      setThreadId(result.thread_id);
      setExchanges((current) => [
        { question: asked, reply: result.reply, actions: result.actions },
        ...current,
      ]);
      setRemembered(result.remember);
      setContext(result.context);
      setQuestion('');
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Question impossible.', 'recover');
    },
  });

  function send(asked: string): void {
    const cleaned = asked.trim();
    if (cleaned === '') return;
    setRemembered([]);
    ask.mutate(cleaned);
  }

  return (
    <div className={cx('wrap', styles.screen)}>
      <header className={styles.head}>
        <div>
          <p className="eyebrow">Assistant</p>
          <h2 className={styles.title}>
            {opened.data?.title ?? 'Pose une question sur tes données'}
          </h2>
        </div>
        <Button
          variant="ghost"
          aria-haspopup="dialog"
          aria-expanded={threadsOpen}
          onClick={() => {
            setThreadsOpen(true);
          }}
        >
          Discussions
        </Button>
      </header>

      <ThreadSheet
        open={threadsOpen}
        current={threadId}
        onClose={() => {
          setThreadsOpen(false);
        }}
        onOpenThread={(id) => {
          setThreadId(id);
          setExchanges([]);
          setRemembered([]);
          setContext([]);
        }}
      />

      {/* `IA-12` — permanent, jamais repliable : une mention qu'on ferme est une mention
          qu'on ne lit plus. */}
      <p className={styles.caution}>
        L’assistant n’est pas médecin. Il ne pose aucun diagnostic et n’interprète aucun symptôme :
        devant une douleur ou une blessure, va voir un professionnel de santé.
      </p>

      {isPending && <Card>Chargement du carnet…</Card>}

      {error !== null && (
        <Card>
          <Empty title="Assistant indisponible">
            {error instanceof ApiError ? error.message : 'Le serveur est injoignable.'}
          </Empty>
        </Card>
      )}

      {data && (
        <>
          <Card>
            {!enabled && (
              <Empty title="Assistance indisponible">
                {message}
                <br />
                Le carnet, lui, reste utilisable : il se lit et s’écrit à la main.
              </Empty>
            )}

            {enabled && (
              <>
                {/* Le formulaire **avant** le fil, et le fil du plus récent au plus
                    ancien. Le champ reste ainsi à une place fixe près du haut, et la
                    dernière réponse tombe juste en dessous : les deux choses qu'on
                    regarde sont ensemble, quel que soit le nombre de questions posées. */}
                <form
                  className={styles.form}
                  onSubmit={(event) => {
                    event.preventDefault();
                    send(question);
                  }}
                >
                  <Field
                    label="Ta question"
                    value={question}
                    placeholder="Pourquoi je stagne depuis trois semaines ?"
                    onChange={(event) => {
                      setQuestion(event.target.value);
                    }}
                  />

                  {shown.length === 0 && (
                    <div className={styles.examples}>
                      {EXAMPLES.map((example) => (
                        <Chip
                          key={example}
                          selected={false}
                          onClick={() => {
                            setQuestion(example);
                          }}
                        >
                          {example}
                        </Chip>
                      ))}
                    </div>
                  )}

                  <Button
                    type="submit"
                    variant="primary"
                    busy={ask.isPending}
                    disabled={question.trim() === ''}
                    className={styles.submit}
                  >
                    Demander
                  </Button>
                </form>

                {shown.length === 0 && (
                  <Empty title="Rien demandé pour l’instant">
                    L’assistant lit tes chiffres — poids, séances, protéines, hydratation, objectif,
                    planning — et ton carnet. Il ne voit aucun de tes fichiers.
                  </Empty>
                )}

                {remembered.length > 0 && <Remembered notes={remembered} />}

                {shown.map((item, index) => (
                  <div key={`${String(shown.length - index)}-${item.question.slice(0, 24)}`}>
                    <div className={styles.thread}>
                      <div className={cx(styles.turn, styles.mine)}>
                        <span className={styles.role}>Moi</span>
                        {item.question}
                      </div>
                      <div className={cx(styles.turn, styles.theirs)}>
                        <span className={styles.role}>Assistant</span>
                        {item.reply}
                      </div>

                      {/* Sous la réponse qui les a produites, et non en pied d'écran :
                          une action se lit avec la phrase qui l'explique. */}
                      {item.actions.map((report, position) => (
                        <ActionCard key={`${report.name}-${String(position)}`} report={report} />
                      ))}
                    </div>

                    {/* Le condensé accompagne **la** réponse qu'il a produite, et lui
                        seule : il est recalculé à chaque question, et l'afficher une fois
                        pour tout le fil laisserait croire qu'il valait aussi pour les
                        précédentes. `IA-09` rendu vérifiable plutôt que déclaratif. */}
                    {index === 0 && context.length > 0 && (
                      <details className={styles.facts}>
                        <summary>
                          Ce qui a été envoyé au modèle ({context.length} lignes, aucun fichier)
                        </summary>
                        <ul>
                          {context.map((line) => (
                            <li key={line}>{line}</li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </div>
                ))}
              </>
            )}
          </Card>

          <MemoryCard entries={data.memories} topics={data.topics} />
        </>
      )}
    </div>
  );
}
