/**
 * Le tableau de bord.
 *
 * ## Ce que la refonte a changé, et pourquoi
 *
 * L'écran empilait quatre tuiles de poids égal, une carte « Assistant » qui ne contenait
 * que trois boutons, puis une tendance. Il disait **où j'en suis** et jamais **ce que ça
 * vaut**, ni **ce qui vient ensuite** — et rien n'y indiquait quoi regarder en premier.
 *
 * Il se lit maintenant de haut en bas comme une journée :
 *
 * 1. **la lecture du jour** — un message de l'assistant sur la situation du moment, dont
 *    le corps se touche pour lui répondre dans un fil qui commence dessus ;
 * 2. **il reste aujourd'hui** — l'eau, les protéines, les suppléments et la séance prévue,
 *    avec l'écart qui reste sur chacun ;
 * 3. **où je vais** — l'objectif en cours et sa progression, qui n'étaient sur aucun écran
 *    d'accueil ;
 * 4. la tendance et l'entraînement, inchangés.
 *
 * ## Les trois défauts corrigés au passage
 *
 * * Le conteneur passe à `cx('wrap', styles.screen)`. Il était l'un des huit écrans encore
 *   sur `className="wrap"` seul, dont `.wrap .wrap` masquait la conséquence.
 * * L'histogramme des huit semaines dérivait sa part d'un `Math.max(...weeks.map(…))`.
 *   Un maximum sur une série **est** une dérivation ; `WeekVolume.ratio` est servi.
 * * `data.highlight` était transporté et jamais lu. Il l'est toujours — c'est le réglage
 *   de la piste d'assiduité, il appartient à `/assiduite` — mais plus rien ici ne prétend
 *   s'en servir.
 *
 * ## Ce qui n'a pas bougé
 *
 * **Un seul appel pour les indicateurs** (`AGG-01`). La lecture du jour en ajoute un
 * second, indépendant, avec ses propres quatre états : l'écran peint entièrement sans
 * l'attendre, et la latence d'un modèle n'est jamais payée par les chiffres.
 */

import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import {
  Badge,
  Bars,
  Card,
  Chart,
  Chip,
  ChipStrip,
  Empty,
  LinkButton,
  PageHead,
  Rule,
  Segmented,
} from '@/components/ui';
import {
  aggregatesApi,
  type DashboardView,
  type RangeKey,
  type SeriesView,
  type Streak,
} from '@/features/aggregates/api';
import { cx } from '@/lib/cx';
import {
  dayMonth,
  dayOfMonth,
  delta,
  hoursMinutes,
  integer,
  longDate,
  num,
  plural,
} from '@/lib/format';
import { keys } from '@/lib/query';

import { Aim } from './dashboard/Aim';
import { Brief } from './dashboard/Brief';
import { Today } from './dashboard/Today';
import styles from './Dashboard.module.css';

/** Les trois plages du contrat `AGG-04`. Le serveur refuse tout le reste. */
const RANGES = [
  { value: '1m', label: '1 mois' },
  { value: '3m', label: '3 mois' },
  { value: 'all', label: 'Tout' },
] as const satisfies readonly { value: RangeKey; label: string }[];

/** Ce qu'un jour de la série d'assiduité doit à chaque domaine. */
const SOURCE_LABELS: Record<string, string> = {
  weight: 'poids',
  measurements: 'mensurations',
  runs: 'course',
  workouts: 'séance',
  meals: 'repas',
  hydration: 'hydratation',
  supplements: 'suppléments',
};

// ── Graphique croisé (`AGG-04`) ───────────────────────

function Graph({ shipped }: { shipped: SeriesView }) {
  // L'état part **vide** : la métrique et la plage affichées sont celles que le serveur a
  // livrées avec le tableau de bord. Le client ne code donc aucun défaut, et le premier
  // rendu ne déclenche aucune seconde requête (`AGG-01`).
  const [choice, setChoice] = useState<{ metric: string; range: RangeKey } | null>(null);

  const { data: catalogue } = useQuery({
    queryKey: keys.aggregates.metrics(),
    queryFn: aggregatesApi.metrics,
  });

  const metric = choice?.metric ?? shipped.metric;
  const range = choice?.range ?? shipped.range;

  const custom = useQuery({
    queryKey: keys.aggregates.series(metric, range),
    queryFn: () => aggregatesApi.series(metric, range),
    // Tant que rien n'a été choisi, la série livrée avec le tableau de bord suffit :
    // cette requête ne part pas, et le chargement de l'écran reste un seul appel.
    enabled: choice !== null,
  });

  const series = choice === null ? shipped : custom.data;

  // Les métriques paramétrées — la charge d'un exercice — demandent un sujet que ce
  // sélecteur ne propose pas encore : elles vivent sur l'écran Activité.
  const options = (catalogue ?? []).filter((entry) => entry.subjects.length === 0);

  return (
    <Card>
      <div className={styles.graphHead}>
        <div>
          <h3>{series?.label ?? shipped.label}</h3>
          <p className={styles.note}>
            {series && series.stats.count > 0
              ? `${integer(series.stats.count)} ${plural(series.stats.count, 'relevé')} sur la plage`
              : 'Aucun relevé sur cette plage.'}
          </p>
        </div>
        <Segmented
          options={RANGES}
          value={range}
          onChange={(next) => {
            setChoice({ metric, range: next });
          }}
          label="Plage du graphique"
        />
      </div>

      {/* Treize métriques dans une liste qui passe à la ligne prenaient **neuf lignes et
          470 px** sur un téléphone — plus d'une demi-hauteur d'écran pour un sélecteur —
          et chaque bouton faisait 28 px de haut. Une bande qui se tire au pouce en prend
          50, et chaque pastille respecte le plancher tactile. */}
      {options.length > 1 && (
        <div className={styles.metrics}>
          <ChipStrip label="Métrique du graphique">
            {options.map((entry) => (
              <Chip
                key={entry.key}
                selected={entry.key === metric}
                onClick={() => {
                  setChoice({ metric: entry.key, range });
                }}
              >
                {entry.label}
              </Chip>
            ))}
          </ChipStrip>
        </div>
      )}

      {custom.isPending && choice !== null ? (
        <p className={styles.empty}>chargement…</p>
      ) : series === undefined || series.points.length < 2 ? (
        <p className={styles.empty}>
          Deux relevés suffisent pour tracer une courbe. Il en manque encore.
        </p>
      ) : (
        <>
          <Chart
            labels={series.points.map((point) => dayMonth(point.date))}
            primary={{
              label: series.label,
              values: series.points.map((point) => point.value),
              tone: 'signal',
              unit: series.unit,
              format: (value) => num(value, 1),
            }}
          />
          <div className={styles.seriesStats}>
            {/* Tous ces chiffres viennent du serveur : le client n'en dérive aucun. */}
            <span>
              dernier <b className="num">{num(series.stats.latest ?? 0, 1)}</b> {series.unit}
            </span>
            {series.stats.change !== null && (
              <span>
                variation{' '}
                <b className="num">
                  {delta(series.stats.change)} {series.unit}
                </b>
              </span>
            )}
            {series.stats.average !== null && (
              <span>
                moyenne <b className="num">{num(series.stats.average, 1)}</b> {series.unit}
              </span>
            )}
            {series.stats.minimum !== null && series.stats.maximum !== null && (
              <span>
                amplitude{' '}
                <b className="num">
                  {num(series.stats.minimum, 1)} – {num(series.stats.maximum, 1)}
                </b>
              </span>
            )}
          </div>
        </>
      )}
    </Card>
  );
}

// ── Assiduité (`AGG-03`) ──────────────────────────────

function Assiduity({ streak }: { streak: Streak }) {
  return (
    <Card>
      <div className="spread">
        <div>
          <h3>Sept derniers jours</h3>
          <p className={styles.note}>Au moins une donnée, toutes sources confondues.</p>
        </div>
        <Badge tone={streak.current > 0 ? 'effort' : 'load'} mono>
          {integer(streak.current)} j
        </Badge>
      </div>

      <div className={styles.week}>
        {streak.last_seven.map((day) => (
          <div
            key={day.date}
            className={day.active ? styles.dayOn : styles.dayOff}
            title={`${dayMonth(day.date)} — ${
              day.sources.length > 0
                ? day.sources.map((source) => SOURCE_LABELS[source] ?? source).join(', ')
                : 'aucune donnée'
            }`}
          >
            <span className={styles.dayLabel}>{dayOfMonth(day.date)}</span>
            <span className={styles.daySources}>
              {day.active ? integer(day.sources.length) : '—'}
            </span>
          </div>
        ))}
      </div>
    </Card>
  );
}

// ── Entraînement ──────────────────────────────────────

function Training({ training }: { training: DashboardView['training'] }) {
  return (
    <div className="grid g2">
      <Card>
        <div className="spread">
          <div>
            <h3>Huit dernières semaines</h3>
            <p className={styles.note}>
              {integer(training.sessions_total)} {plural(training.sessions_total, 'séance')} depuis
              le début, soit {hoursMinutes(training.minutes_total)}.
            </p>
          </div>
        </div>

        {training.sessions_total === 0 ? (
          <p className={styles.empty}>Une première séance, et l’histogramme démarre.</p>
        ) : (
          <Bars
            rows={training.weeks.map((week) => ({
              label: dayMonth(week.week_start),
              // **Servie.** Elle était dérivée d'un `Math.max` sur la série entière, ce
              // qui est un calcul métier — le défaut que ce lot corrige.
              ratio: week.ratio,
              value: week.minutes > 0 ? hoursMinutes(week.minutes) : '—',
              tone: 'effort' as const,
            }))}
          />
        )}
      </Card>

      <Card>
        <h3>Répartition</h3>
        <p className={styles.note}>Course et tabata, en séances et en minutes.</p>

        {training.split.length === 0 ? (
          <p className={styles.empty}>Rien à répartir pour l’instant.</p>
        ) : (
          <Bars
            rows={training.split.map((part) => ({
              label: part.label,
              ratio: part.ratio,
              value: `${integer(part.sessions)} · ${hoursMinutes(part.minutes)}`,
              tone: part.kind === 'run' ? ('signal' as const) : ('effort' as const),
            }))}
          />
        )}
      </Card>
    </div>
  );
}

// ── Écran ─────────────────────────────────────────────

export function Dashboard() {
  // **Un seul appel pour les indicateurs** (`AGG-01`) : chiffres du jour, journée à finir,
  // objectif, séance à venir, assiduité et série du graphique arrivent ensemble.
  const { data, isPending, error } = useQuery({
    queryKey: keys.aggregates.dashboard(),
    queryFn: () => aggregatesApi.dashboard(),
  });

  if (isPending) {
    return (
      <div className={cx('wrap', styles.screen)}>
        {/* L'en-tête est là **avant** la donnée. Un écran qui n'affiche qu'un
            « chargement… » sur fond noir ne dit pas où l'on vient d'arriver, et la seconde
            d'attente se lit comme un écran qui n'a pas répondu. */}
        <PageHead eyebrow="Aujourd’hui" title="Tableau de bord" />
        <p className={styles.empty}>chargement…</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className={cx('wrap', styles.screen)}>
        <PageHead eyebrow="Aujourd’hui" title="Tableau de bord" />
        <Empty title="Tableau de bord indisponible">
          {error instanceof Error ? error.message : 'Le serveur n’a pas répondu.'}
        </Empty>
      </div>
    );
  }

  return (
    <div className={cx('wrap', styles.screen)}>
      <PageHead eyebrow={longDate(data.date)} title="Tableau de bord" />

      {/* En tête d'écran, et c'est la décision de forme du lot. L'ancienne carte
          d'assistant venait après les chiffres, « parce qu'une question se pose en
          regardant ce qu'on vient de lire » — vrai d'une carte qui ne contenait que des
          boutons. Une lecture qui **dit** quelque chose répond à la question avant qu'on
          la pose, et c'est elle qu'on veut le matin. `AiBlock` existe exactement pour
          qu'un texte proposé puisse se poser là sans se faire prendre pour une mesure. */}
      <Brief />

      <Today data={data} />

      <Aim data={data} />

      <Rule>Tendance</Rule>
      <div className={styles.split}>
        <Graph shipped={data.series} />
        <Assiduity streak={data.streak} />
      </div>

      <Rule>Entraînement</Rule>
      <Training training={data.training} />

      {/* Les deux portes de côté de l'assistant, et la sienne propre.
          Elles restent **quoi qu'il arrive** : sans clé OpenRouter la lecture du jour ne
          s'affiche pas (`IA-07`), et sur ordinateur cette rangée est la seule entrée vers
          `/assistant` — la barre du haut n'en a pas.
          Une adresse et non un état d'écran : la feuille s'ouvre à l'arrivée, le bouton
          système « précédent » la referme, et le lien se garde en favori. */}
      <Rule>Assistant</Rule>
      <div className={cx('row', styles.doors)}>
        <LinkButton variant="ghost" to="/assistant">
          Ouvrir l’assistant
        </LinkButton>
        <LinkButton variant="ghost" to="/assistant?ouvre=discussions">
          Discussions
        </LinkButton>
        <LinkButton variant="ghost" to="/assistant?ouvre=memoire">
          Mémoire
        </LinkButton>
      </div>
    </div>
  );
}
