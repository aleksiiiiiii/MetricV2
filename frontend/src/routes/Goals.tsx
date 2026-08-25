import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router';

import { AiBlock, Badge, Button, Card, Empty, Field, Ring, Rule } from '@/components/ui';
import { useAiStatus } from '@/features/ai/useAiStatus';
import {
  goalsApi,
  type ActiveGoal,
  type GoalEntry,
  type GoalProposal,
  type WeeklyReview,
} from '@/features/goals/api';
import { ApiError } from '@/lib/api';
import { celebrate } from '@/lib/confetti';
import { cx } from '@/lib/cx';
import { num, plural, shortDate } from '@/lib/format';
import { CROSS_CUTTING, keys } from '@/lib/query';
import { useToast } from '@/lib/toast';

import styles from './Goals.module.css';

/**
 * Écran Objectif (`L14-09`).
 *
 * ## Ce que l'écran ne fait pas
 *
 * Il ne calcule aucun avancement. Le ratio, le libellé chiffré, la fenêtre d'observation
 * et les jours restants arrivent **calculés** : deux implémentations d'une même
 * progression divergent au premier cas limite, et c'est l'utilisateur qui arbitrerait
 * entre deux pourcentages du même objectif (`HEAT-30`).
 *
 * Il ne décide pas non plus du résultat final. « Atteint » ou « partiel » est une lecture
 * des données, faite par le serveur : laisser l'écran cocher « atteint » reviendrait à
 * laisser cocher « atteint » un objectif qui ne l'est pas (`GOAL-06`).
 *
 * ## Les trois états de `GOAL-05`
 *
 * Deux viennent du serveur — aucune proposition, objectif actif. Le troisième, « en
 * attente », vit **ici seulement** : une proposition non adoptée n'existe nulle part et
 * se perd au rechargement. C'est la traduction exacte de « rien n'est écrit sans
 * validation ». Le même `AiBlock` que la nutrition, l'import et le planning le dit, plutôt
 * qu'une quatrième façon d'annoncer qu'une valeur n'est pas encore une donnée.
 */

function useInvalidateGoals() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: keys.goals.all() });
    for (const key of CROSS_CUTTING) void client.invalidateQueries({ queryKey: key });
  };
}

/** Jours restants, en clair. Le serveur donne le nombre ; le français est ici. */
function deadlineLine(days: number, deadline: string): string {
  const when = shortDate(`${deadline}T12:00:00`);
  if (days < 0)
    return `échéance dépassée depuis ${String(-days)} ${plural(-days, 'jour')} — ${when}`;
  if (days === 0) return `dernier jour — ${when}`;
  return `${String(days)} ${plural(days, 'jour')} ${plural(days, 'restant')} — ${when}`;
}

// ── L'objectif en cours (`GOAL-04`, `GOAL-05`) ────────

function CurrentGoal({ active }: { active: ActiveGoal }) {
  const invalidate = useInvalidateGoals();
  const { notify } = useToast();
  const [armed, setArmed] = useState(false);

  const { goal, progress } = active;

  const finish = useMutation({
    mutationFn: (mode: 'close' | 'abandon') =>
      mode === 'close'
        ? goalsApi.close(goal.id, goal.token)
        : goalsApi.abandon(goal.id, goal.token),
    onSuccess: (entry) => {
      setArmed(false);
      invalidate();
      // **Atteint, pas abandonné.** C'est toute la distinction : un objectif clos parce
      // qu'on y est arrivé se fête, un objectif abandonné se respecte en silence.
      if (entry.outcome === 'reached') celebrate();
      notify(
        `Objectif clos : ${entry.outcome_label}.`,
        entry.outcome === 'reached' ? 'effort' : 'signal',
      );
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Clôture impossible.', 'recover');
    },
  });

  return (
    <Card>
      <div className="spread">
        <div>
          <p className="eyebrow">Objectif en cours</p>
          <h3>{goal.title}</h3>
        </div>
        {active.expired && <Badge tone="recover">échéance passée</Badge>}
      </div>

      <div className={styles.current}>
        {/* **Pas d'anneau du tout** quand l'avancement est indéterminé.
            Première version : un anneau vide avec « rien à mesurer encore » à côté. Vue
            dans le navigateur, elle affichait un « 0% » au centre — c'est-à-dire une
            valeur inventée à l'écran, exactement ce que l'invariant interdit, et le
            chiffre est ce que l'œil lit en premier. Un disque creux ne ment pas. */}
        {progress.ratio === null ? (
          <div className={styles.noRing} role="img" aria-label="avancement indéterminé">
            —
          </div>
        ) : (
          <Ring
            ratio={progress.ratio}
            label={progress.label}
            tone={progress.ratio >= 1 ? 'effort' : 'signal'}
          />
        )}

        <div className={styles.figures}>
          <span className={styles.summary}>{progress.summary}</span>
          <span className={styles.basis}>
            {progress.ratio === null
              ? 'avancement indéterminé — rien n’avait été relevé au moment de l’adoption'
              : progress.basis}
          </span>
          {goal.rationale !== '' && <span className={styles.basis}>{goal.rationale}</span>}
        </div>
      </div>

      <div className={styles.stats}>
        <div className={styles.stat}>
          <span className={styles.statKey}>Départ</span>
          <span className={styles.statValue}>
            {progress.baseline === null ? '—' : num(progress.baseline, 1)}
          </span>
        </div>
        <div className={styles.stat}>
          <span className={styles.statKey}>Cible</span>
          <span className={styles.statValue}>{num(progress.target, 1)}</span>
        </div>
        <div className={styles.stat}>
          <span className={styles.statKey}>Reste</span>
          <span className={styles.statValue}>{active.days_left} j</span>
        </div>
      </div>

      <p className={styles.basis}>{deadlineLine(active.days_left, goal.deadline)}</p>

      <div className={styles.actions}>
        <Button
          variant="primary"
          busy={finish.isPending}
          onClick={() => {
            finish.mutate('close');
          }}
        >
          Clore l&apos;objectif
        </Button>

        {/* Deux appuis pour abandonner : le projet n'a pas d'annulation, et un objectif
            abandonné change ce que la génération suivante proposera (`GOAL-06`). */}
        <Button
          variant="quiet"
          busy={finish.isPending}
          aria-label={armed ? `Abandonner ${goal.title} — confirmer` : `Abandonner ${goal.title}`}
          onClick={() => {
            if (!armed) {
              setArmed(true);
              return;
            }
            finish.mutate('abandon');
          }}
        >
          {armed ? 'Confirmer ?' : 'Abandonner'}
        </Button>
      </div>

      <p className={styles.basis}>
        « Clore » note le résultat que disent les chiffres — atteint ou partiel. « Abandonner » dit
        qu&apos;on n&apos;en voulait plus. Les deux ne racontent pas la même chose à la proposition
        suivante.
      </p>
    </Card>
  );
}

// ── Proposition assistée (`GOAL-01` → `GOAL-03`) ──────

function ProposalCard() {
  const invalidate = useInvalidateGoals();
  const { notify } = useToast();
  const { enabled } = useAiStatus();

  const [focus, setFocus] = useState('');
  const [proposal, setProposal] = useState<GoalProposal | null>(null);
  const [title, setTitle] = useState('');

  const ask = useMutation({
    mutationFn: () => goalsApi.propose(focus),
    onSuccess: (result) => {
      setProposal(result);
      setTitle(result.goal.title);
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Proposition impossible.', 'recover');
    },
  });

  const adopt = useMutation({
    mutationFn: (goal: GoalProposal['goal']) =>
      goalsApi.adopt({
        title: title.trim() || goal.title,
        metric: goal.metric,
        target: goal.target,
        deadline: goal.deadline,
        rationale: goal.rationale,
      }),
    onSuccess: () => {
      setProposal(null);
      setFocus('');
      invalidate();
      notify('Objectif adopté.', 'effort');
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Adoption impossible.', 'recover');
    },
  });

  if (!enabled) return null;

  return (
    <Card>
      <div>
        <h3>Se fixer un objectif</h3>
        <p className={styles.note}>
          Un seul objectif, chiffré, daté de quatre à huit semaines, appuyé sur ce que disent tes
          données. Rien n&apos;est écrit tant que tu n&apos;as pas adopté.
        </p>
      </div>

      <div className={styles.form}>
        <Field
          label="Ce que tu veux travailler"
          value={focus}
          placeholder="courir plus régulièrement, perdre du ventre"
          hint="Facultatif — sans rien, la proposition ne s'appuie que sur les chiffres."
          onChange={(event) => {
            setFocus(event.target.value);
          }}
        />

        <Button
          variant="primary"
          busy={ask.isPending}
          className={styles.submit}
          onClick={() => {
            ask.mutate();
          }}
        >
          {proposal ? 'Proposer autre chose' : 'Proposer un objectif'}
        </Button>
      </div>

      {proposal && (
        <AiBlock
          tag="Proposition"
          actions={
            <>
              <Button
                variant="primary"
                busy={adopt.isPending}
                onClick={() => {
                  adopt.mutate(proposal.goal);
                }}
              >
                Adopter
              </Button>
              <Button
                variant="quiet"
                onClick={() => {
                  setProposal(null);
                }}
              >
                Pas d&apos;accord
              </Button>
            </>
          }
        >
          <div className={styles.proposed}>
            <span className={styles.target}>
              {num(proposal.goal.target, 1)} {proposal.goal.unit}
            </span>
            <span className={styles.note}>
              {proposal.goal.label} · échéance {shortDate(`${proposal.goal.deadline}T12:00:00`)}
            </span>
            {proposal.goal.rationale !== '' && (
              <span className={styles.note}>{proposal.goal.rationale}</span>
            )}
          </div>

          {/* Le titre se retouche avant adoption. Le retoucher fait sienne la proposition
              — c'est la même règle qu'une macro estimée puis corrigée (`NUT-04`). */}
          <Field
            label="Titre de l'objectif"
            value={title}
            placeholder="Trois séances par semaine"
            onChange={(event) => {
              setTitle(event.target.value);
            }}
          />

          {proposal.fallback && (
            <p className={styles.note}>
              Les données sont encore trop maigres pour viser une performance : la proposition porte
              sur la régularité, qui est le seul chiffre qui ait un sens tant que la fréquence
              n&apos;est pas établie.
            </p>
          )}

          {/* `GOAL-02` rendu vérifiable plutôt que déclaratif : voici exactement ce qui a
              été envoyé au modèle. Replié, parce qu'on ne le lit pas à chaque fois. */}
          <details className={styles.facts}>
            <summary>Ce qui a été envoyé au modèle ({proposal.basis.length} lignes)</summary>
            <ul>
              {proposal.basis.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </details>

          {proposal.dropped.length > 0 && (
            <p className={styles.dropped}>Écarté à la relecture : {proposal.dropped.join(' ')}</p>
          )}
        </AiBlock>
      )}
    </Card>
  );
}

// ── Bilan hebdomadaire (`IA-08`) ──────────────────────

function WeeklyCard() {
  const client = useQueryClient();
  const { notify } = useToast();
  const { enabled } = useAiStatus();
  const [review, setReview] = useState<WeeklyReview | null>(null);

  const { data } = useQuery({ queryKey: keys.goals.weekly(), queryFn: goalsApi.weekly });

  const ask = useMutation({
    mutationFn: goalsApi.review,
    onSuccess: setReview,
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Bilan impossible.', 'recover');
    },
  });

  const keep = useMutation({
    mutationFn: (item: WeeklyReview) => goalsApi.keep(item.week, summaryOf(item)),
    onSuccess: () => {
      setReview(null);
      void client.invalidateQueries({ queryKey: keys.goals.all() });
      notify('Bilan conservé.', 'effort');
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Impossible de conserver.', 'recover');
    },
  });

  if (!data) return null;

  return (
    <Card>
      <div className="spread">
        <div>
          <h3>Bilan de la semaine</h3>
          <p className={styles.note}>
            Semaine du {shortDate(`${data.next_week}T12:00:00`)} — la dernière achevée. Ce qui a
            progressé, ce qui a décroché, une action pour celle qui commence.
          </p>
        </div>
      </div>

      {enabled && (
        <div className={styles.form}>
          <Button
            variant="primary"
            busy={ask.isPending}
            className={styles.submit}
            onClick={() => {
              ask.mutate();
            }}
          >
            {data.already_kept ? 'Refaire le bilan' : 'Faire le bilan'}
          </Button>
          {data.already_kept && (
            <p className={styles.note}>
              Cette semaine a déjà son bilan. En conserver un autre remplacera le précédent — une
              semaine, une ligne.
            </p>
          )}
        </div>
      )}

      {review && (
        <AiBlock
          tag="Bilan"
          actions={
            <>
              <Button
                variant="primary"
                busy={keep.isPending}
                onClick={() => {
                  keep.mutate(review);
                }}
              >
                Conserver
              </Button>
              <Button
                variant="quiet"
                onClick={() => {
                  setReview(null);
                }}
              >
                Jeter
              </Button>
            </>
          }
        >
          <div className={styles.review}>
            {review.progress.length > 0 && (
              <div className={styles.reviewGroup}>
                <span className="eyebrow">Ce qui progresse</span>
                <ul>
                  {review.progress.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </div>
            )}

            {review.setbacks.length > 0 && (
              <div className={styles.reviewGroup}>
                <span className="eyebrow">Ce qui décroche</span>
                <ul>
                  {review.setbacks.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ul>
              </div>
            )}

            {review.action !== '' && <p className={styles.action}>{review.action}</p>}
          </div>

          <details className={styles.facts}>
            <summary>Ce qui a été envoyé au modèle ({review.basis.length} lignes)</summary>
            <ul>
              {review.basis.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </details>
        </AiBlock>
      )}

      {data.entries.length > 0 && (
        <>
          <Rule>Bilans conservés</Rule>
          <ul className={styles.list}>
            {data.entries.map((entry) => (
              <li key={entry.week} className={styles.item}>
                <div className={styles.itemBody}>
                  <span className={styles.meta}>
                    semaine du {shortDate(`${entry.week}T12:00:00`)}
                  </span>
                  <span>{entry.summary}</span>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}

/** Le bilan en une phrase — la forme d'une cellule de tableur, comme côté serveur. */
function summaryOf(review: WeeklyReview): string {
  const parts: string[] = [];
  if (review.progress.length > 0) parts.push(`Progrès : ${review.progress.join(' ')}`);
  if (review.setbacks.length > 0) parts.push(`Décrochages : ${review.setbacks.join(' ')}`);
  if (review.action !== '') parts.push(`Action : ${review.action}`);
  return parts.join(' — ');
}

// ── Historique (`GOAL-06`) ────────────────────────────

function History({ entries }: { entries: GoalEntry[] }) {
  if (entries.length === 0) return null;

  return (
    <Card>
      <h3>Objectifs passés</h3>
      <p className={styles.note}>
        Ils servent à la proposition suivante : un objectif abandonné ne se repropose pas à
        l&apos;identique.
      </p>

      <ul className={styles.list}>
        {entries.map((entry) => (
          <li key={entry.goal_id} className={styles.item}>
            <div className={styles.itemBody}>
              <strong>{entry.title}</strong>
              <span className={styles.meta}>
                {num(entry.target, 1)} {entry.unit} · échéance{' '}
                {shortDate(`${entry.deadline}T12:00:00`)}
              </span>
            </div>
            <Badge tone={entry.outcome === 'reached' ? 'effort' : 'load'}>
              {entry.outcome_label || '—'}
            </Badge>
          </li>
        ))}
      </ul>
    </Card>
  );
}

// ── Écran ─────────────────────────────────────────────

export function Goals() {
  const { enabled, message } = useAiStatus();
  const { data, isPending, error } = useQuery({
    queryKey: keys.goals.active(),
    queryFn: goalsApi.view,
  });

  return (
    <div className={cx('wrap', styles.screen)}>
      <header className={styles.head}>
        <p className="eyebrow">Objectif</p>
        <h2 className={styles.title}>Une cible, chiffrée, datée</h2>
      </header>

      {isPending && <Card>Chargement de l&apos;objectif…</Card>}

      {error !== null && (
        <Card>
          <Empty title="Objectif indisponible">
            {error instanceof ApiError ? error.message : 'Le serveur est injoignable.'}
          </Empty>
        </Card>
      )}

      {data && (
        <>
          {data.active ? (
            <CurrentGoal active={data.active} />
          ) : (
            <Card>
              <Empty title="Aucun objectif en cours">
                {enabled
                  ? 'Une cible chiffrée sur six semaines change ce qu’on regarde le matin. La proposition part de tes quatre dernières semaines.'
                  : message}
              </Empty>
            </Card>
          )}

          {/* Seconde porte de l'écran Assistant, qui n'a pas d'entrée de navigation.
              Elle est ici parce que l'assistant reçoit l'objectif actif dans son condensé :
              « pourquoi je n'avance pas ? » se pose devant cet anneau, pas ailleurs. */}
          <p className={styles.basis}>
            <Link className={styles.assistant} to="/assistant">
              Demander à l’assistant
            </Link>
          </p>

          {!data.active && <ProposalCard />}
          <WeeklyCard />
          <History entries={data.history} />
        </>
      )}
    </div>
  );
}
