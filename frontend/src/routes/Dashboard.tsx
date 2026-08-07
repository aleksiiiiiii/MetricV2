import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'react-router';

import {
  Badge,
  Bars,
  Card,
  Chart,
  Chip,
  ChipStrip,
  Empty,
  PageHead,
  Progress,
  Rule,
  Segmented,
  Stat,
} from '@/components/ui';
import {
  aggregatesApi,
  type DashboardView,
  type RangeKey,
  type SeriesView,
  type Streak,
} from '@/features/aggregates/api';
import {
  dayMonth,
  delta,
  hoursMinutes,
  integer,
  kg,
  longDate,
  num,
  percent,
  plural,
  volume,
} from '@/lib/format';
import { keys } from '@/lib/query';

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

// ── Rangée de chiffres clés ───────────────────────────

function Numbers({ data }: { data: DashboardView }) {
  const { weight, training, hydration, streak } = data;

  return (
    // `tiles` et non `g4` : ces quatre-là sont un libellé, un chiffre et une ligne de
    // détail — ils tiennent deux de front dès 390 px. Empilés, il fallait faire défiler
    // pour lire son poids **et** sa semaine, alors que la comparaison est tout l'intérêt.
    <div className="grid tiles">
      <Card>
        <Stat
          compact
          label="Poids"
          value={weight.latest_kg !== null ? num(weight.latest_kg, 1) : '—'}
          unit={weight.latest_kg !== null ? 'kg' : undefined}
          detail={
            weight.change_kg !== null
              ? `${delta(weight.change_kg)} kg sur les 8 dernières pesées`
              : weight.latest_kg !== null
                ? // Il y a un chiffre : lui dire d'en poser un se lisait comme un écran
                  // qui n'a pas vu la pesée qu'il affiche juste au-dessus.
                  'Première pesée. La tendance vient à la deuxième.'
                : 'Un chiffre le matin, et la courbe commence.'
          }
          direction={weight.change_kg === null ? undefined : weight.change_kg > 0 ? 'up' : 'down'}
        />
      </Card>

      <Card>
        <Stat
          compact
          label="Cette semaine"
          value={training.week.sessions > 0 ? hoursMinutes(training.week.minutes) : '—'}
          detail={
            training.week.sessions > 0
              ? `${integer(training.week.sessions)} ${plural(training.week.sessions, 'séance')}, ${num(training.week.distance_km, 1)} km`
              : 'Rien depuis lundi.'
          }
        />
      </Card>

      <Card>
        <Stat
          compact
          label="Hydratation"
          value={hydration.today_ml > 0 ? volume(hydration.today_ml) : '—'}
          // Le pourcentage n'accompagne le tiret que s'il y a bu quelque chose : « — » et
          // « 0 % » côte à côte disent la même absence de deux façons dont l'une ressemble
          // à une mesure.
          detail={
            hydration.today_ml > 0
              ? `objectif ${volume(hydration.target_ml)} · ${percent(hydration.ratio)}`
              : `objectif ${volume(hydration.target_ml)}`
          }
        />
      </Card>

      <Card>
        <Stat
          compact
          label="Assiduité"
          value={streak.current > 0 ? integer(streak.current) : '—'}
          unit={streak.current > 0 ? (streak.current > 1 ? 'jours' : 'jour') : undefined}
          detail={
            streak.longest > 0
              ? `record ${integer(streak.longest)} jours · ${integer(streak.active_days)} jours suivis`
              : 'Une donnée, n’importe laquelle, et la série démarre.'
          }
        />
      </Card>
    </div>
  );
}

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
          50, et chaque pastille respecte le plancher tactile. C'est exactement ce pour
          quoi `ChipStrip` existe ; il n'était employé que sur deux écrans. */}
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
            labelEvery={Math.max(1, Math.ceil(series.points.length / 8))}
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
            title={
              day.sources.length > 0
                ? day.sources.map((source) => SOURCE_LABELS[source] ?? source).join(', ')
                : 'aucune donnée'
            }
          >
            <span className={styles.dayLabel}>{dayMonth(day.date)}</span>
            <span className={styles.daySources}>
              {day.active ? integer(day.sources.length) : '—'}
            </span>
          </div>
        ))}
      </div>
    </Card>
  );
}

// ── Écran ─────────────────────────────────────────────

export function Dashboard() {
  // **Un seul appel au chargement** (`AGG-01`) : indicateurs, totaux, assiduité et série
  // du graphique arrivent ensemble. C'est la raison d'être du lot L08.
  const { data, isPending, error } = useQuery({
    queryKey: keys.aggregates.dashboard(),
    queryFn: () => aggregatesApi.dashboard(),
  });

  if (isPending) {
    return (
      <div className="wrap">
        <p className={styles.empty}>chargement…</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="wrap">
        <Empty title="Tableau de bord indisponible">
          {error instanceof Error ? error.message : 'Le serveur n’a pas répondu.'}
        </Empty>
      </div>
    );
  }

  const nothingToday =
    data.nutrition.meals === 0 &&
    data.hydration.today_ml === 0 &&
    data.supplements.taken === 0 &&
    (data.weight.latest_date ?? '') !== data.date;

  return (
    <div className="wrap">
      <PageHead eyebrow={longDate(data.date)} title="Tableau de bord" />

      <Rule>Aujourd’hui</Rule>

      {nothingToday && (
        <Empty title="Aucun relevé aujourd’hui">
          Deux chiffres suffisent pour que la journée compte.
          <br />
          <Link to="/corps">Une pesée</Link>, <Link to="/routine">un verre d’eau</Link>, et la série
          tient.
        </Empty>
      )}

      <Numbers data={data} />

      {/* La porte de l'assistant. Il n'a **pas** d'entrée de navigation — la barre
          demandait déjà 806 px pour 695 disponibles — et cette carte est donc son accès
          principal : elle vient tout de suite après les chiffres du jour, avant la
          tendance, parce qu'une question se pose en regardant ce qu'on vient de lire. */}
      <Rule>Demander</Rule>
      <Card>
        <div className="spread">
          <div>
            <h3>Une question sur tes chiffres ?</h3>
            <p className={styles.empty}>
              L’assistant lit ton poids, tes séances, tes macros, ton objectif et ton planning — et
              ce que tu lui as dit de retenir.
            </p>
          </div>
        </div>
        <div className="row mt">
          <Link className={styles.assistant} to="/assistant">
            Ouvrir l’assistant
          </Link>
        </div>
      </Card>

      <Rule>Tendance</Rule>
      <div className={styles.split}>
        <Graph shipped={data.series} />

        <div className="stack">
          <Assiduity streak={data.streak} />

          <Card>
            <div className="spread">
              <h3>Journée</h3>
              <Badge tone={data.nutrition.over_sugar ? 'recover' : 'signal'} mono>
                {integer(data.nutrition.meals)} repas
              </Badge>
            </div>

            <div className={styles.rows}>
              <div>
                <span className={styles.rowLabel}>Protéines</span>
                <Progress
                  done={Math.round(data.nutrition.protein_g)}
                  total={Math.round(data.nutrition.protein_target_g)}
                />
              </div>
              <div>
                <span className={styles.rowLabel}>Hydratation</span>
                <Progress done={data.hydration.today_ml} total={data.hydration.target_ml} />
              </div>
              <div>
                <span className={styles.rowLabel}>Suppléments</span>
                <Progress done={data.supplements.taken} total={data.supplements.planned} />
              </div>
            </div>

            {data.nutrition.over_sugar && (
              <p className={styles.warn}>
                Plafond de sucres dépassé : {num(data.nutrition.added_sugar_g, 1)} g sur{' '}
                {num(data.nutrition.added_sugar_max_g, 0)} g.
              </p>
            )}
          </Card>
        </div>
      </div>

      <Rule>Entraînement</Rule>
      <div className="grid g2">
        <Card>
          <div className="spread">
            <div>
              <h3>Huit dernières semaines</h3>
              <p className={styles.note}>
                {integer(data.training.sessions_total)}{' '}
                {plural(data.training.sessions_total, 'séance')} depuis le début, soit{' '}
                {hoursMinutes(data.training.minutes_total)}.
              </p>
            </div>
          </div>

          {data.training.sessions_total === 0 ? (
            <p className={styles.empty}>Une première séance, et l’histogramme démarre.</p>
          ) : (
            <Bars
              rows={data.training.weeks.map((week) => ({
                label: dayMonth(week.week_start),
                ratio:
                  week.minutes / Math.max(...data.training.weeks.map((other) => other.minutes), 1),
                value: week.minutes > 0 ? hoursMinutes(week.minutes) : '—',
                tone: 'effort' as const,
              }))}
            />
          )}
        </Card>

        <Card>
          <h3>Répartition</h3>
          <p className={styles.note}>
            Ce qui n’est ni course ni musculation est nommé pour ce qu’il est.
          </p>

          {data.training.split.length === 0 ? (
            <p className={styles.empty}>Rien à répartir pour l’instant.</p>
          ) : (
            <Bars
              rows={data.training.split.map((part) => ({
                label: part.label,
                ratio: part.ratio,
                value: `${integer(part.sessions)} · ${hoursMinutes(part.minutes)}`,
                tone: part.kind === 'run' ? ('signal' as const) : ('effort' as const),
              }))}
            />
          )}
        </Card>
      </div>

      {data.weight.to_target_kg !== null && (
        <>
          <Rule>Objectif</Rule>
          <Card>
            <Stat
              label={`Objectif ${kg(data.weight.target_kg)}`}
              value={num(Math.abs(data.weight.to_target_kg), 1)}
              unit="kg"
              detail={
                data.weight.to_target_kg > 0
                  ? 'restants pour atteindre l’objectif'
                  : 'sous l’objectif'
              }
              direction={data.weight.to_target_kg > 0 ? 'up' : 'down'}
            />
          </Card>
        </>
      )}
    </div>
  );
}
