import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { AiBlock, Badge, Button, Card, Chip, ChipStrip, Empty, Field, Rule } from '@/components/ui';
import { useAiStatus } from '@/features/ai/useAiStatus';
import {
  assistantApi,
  type MemoryEntry,
  type Message,
  type ProposedMemory,
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
 * Il ne décide pas non plus de ce qui mérite d'être retenu. Le modèle propose, l'écran
 * montre, un appui écrit — c'est `NUT-04`, `PLAN-04` et `GOAL-03` appliqués à du texte.
 *
 * ## Le fil ne survit pas au rechargement, et c'est voulu
 *
 * Le serveur ne stocke aucune conversation : c'est cet écran qui lui rend l'historique à
 * chaque question. Un état qui survivrait au rechargement serait un état écrit quelque
 * part, et il n'y a rien à écrire dans un échange dont trois lignes de carnet retiennent
 * l'essentiel.
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
}

/**
 * L'historique tel que le serveur l'attend : **du plus ancien au plus récent**.
 *
 * L'écran affiche l'inverse ; le modèle, lui, lit une conversation dans son ordre. Le
 * retournement vit ici, en un seul endroit, plutôt que dans les deux qui en ont besoin.
 */
function historyOf(exchanges: Exchange[]): Message[] {
  return [...exchanges].reverse().flatMap((item): Message[] => [
    { role: 'user', content: item.question },
    { role: 'assistant', content: item.reply },
  ]);
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
          Note ce qui explique tes chiffres sans y figurer. L’assistant proposera aussi d’en retenir
          au fil des questions.
        </Empty>
      )}

      {entries.length > 0 && (
        <ul className={styles.list}>
          {entries.map((entry) => (
            <li key={entry.memory_id} className={styles.item}>
              <div className={styles.itemBody}>
                <div className={styles.meta}>
                  <span>{entry.topic}</span>
                  {entry.source === 'ai' && <Badge tone="signal">proposée</Badge>}
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

// ── Les notes proposées (`IA-10`) ─────────────────────

function Proposed({ notes, onDone }: { notes: ProposedMemory[]; onDone: () => void }) {
  const invalidate = useInvalidateMemory();
  const { notify } = useToast();
  const [dropped, setDropped] = useState<Set<number>>(new Set());

  const adopt = useMutation({
    mutationFn: async (kept: ProposedMemory[]) => {
      // Une note à la fois : le dépôt n'a pas d'écriture groupée pour ce fichier, et une
      // conversation en propose trois au plus.
      for (const item of kept) await assistantApi.adopt(item.topic, item.note);
    },
    onSuccess: () => {
      invalidate();
      notify('Noté.', 'effort');
      onDone();
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Impossible de retenir.', 'recover');
    },
  });

  const kept = notes.filter((_, index) => !dropped.has(index));

  return (
    <AiBlock
      tag="À retenir ?"
      actions={
        <>
          <Button
            variant="primary"
            busy={adopt.isPending}
            disabled={kept.length === 0}
            onClick={() => {
              adopt.mutate(kept);
            }}
          >
            Retenir {kept.length > 1 ? `(${String(kept.length)})` : ''}
          </Button>
          <Button variant="quiet" onClick={onDone}>
            Pas la peine
          </Button>
        </>
      }
    >
      <p className={styles.note}>
        Rien n’est écrit tant que tu n’as pas retenu. Ce qui l’est repartira avec chaque question
        suivante.
      </p>

      <ul className={styles.proposed}>
        {notes.map((item, index) => (
          <li
            key={`${item.topic}-${item.note}`}
            className={cx(styles.item, dropped.has(index) && styles.itemDropped)}
          >
            <div className={styles.itemBody}>
              <span className={styles.meta}>{item.topic}</span>
              <strong>{item.note}</strong>
            </div>
            <Button
              variant="quiet"
              aria-label={`${dropped.has(index) ? 'Remettre' : 'Retirer'} ${item.note}`}
              onClick={() => {
                setDropped((current) => {
                  const next = new Set(current);
                  if (next.has(index)) next.delete(index);
                  else next.add(index);
                  return next;
                });
              }}
            >
              {dropped.has(index) ? 'Remettre' : 'Retirer'}
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
  const [proposed, setProposed] = useState<ProposedMemory[]>([]);
  const [context, setContext] = useState<string[]>([]);

  const { data, isPending, error } = useQuery({
    queryKey: keys.assistant.memory(),
    queryFn: assistantApi.memory,
  });

  const ask = useMutation({
    mutationFn: (asked: string) => assistantApi.ask(asked, historyOf(exchanges)),
    onSuccess: (result, asked) => {
      setExchanges((current) => [{ question: asked, reply: result.reply }, ...current]);
      setProposed(result.remember);
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
    setProposed([]);
    ask.mutate(cleaned);
  }

  return (
    <div className={cx('wrap', styles.screen)}>
      <header className={styles.head}>
        <p className="eyebrow">Assistant</p>
        <h2 className={styles.title}>Pose une question sur tes données</h2>
      </header>

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

                  {exchanges.length === 0 && (
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

                {exchanges.length === 0 && (
                  <Empty title="Rien demandé pour l’instant">
                    L’assistant lit tes chiffres — poids, séances, protéines, hydratation, objectif,
                    planning — et ton carnet. Il ne voit aucun de tes fichiers.
                  </Empty>
                )}

                {proposed.length > 0 && (
                  <Proposed
                    notes={proposed}
                    onDone={() => {
                      setProposed([]);
                    }}
                  />
                )}

                {exchanges.map((item, index) => (
                  <div key={`${String(exchanges.length - index)}-${item.question.slice(0, 24)}`}>
                    <div className={styles.thread}>
                      <div className={cx(styles.turn, styles.mine)}>
                        <span className={styles.role}>Moi</span>
                        {item.question}
                      </div>
                      <div className={cx(styles.turn, styles.theirs)}>
                        <span className={styles.role}>Assistant</span>
                        {item.reply}
                      </div>
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
