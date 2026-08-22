/**
 * Toutes les courses et ce qu'elles racontent — `/activite/courses` (`ACT-20`).
 *
 * La page Course montre **une** sortie, palier par palier. Celle-ci montre la collection :
 * ce qui a été couru, et ce qui a changé entre les sorties. Les paliers n'existaient que
 * pour la dernière course importée ; sans cette page, ceux de toutes les autres restaient
 * écrits et jamais affichés.
 *
 * ## Le piège de cette page, et il n'est pas celui des paliers
 *
 * `/activite/course` compare huit kilomètres d'une **même** sortie — même personne, même
 * jour, mêmes conditions. Ici on compare des sorties entre elles, et deux allures ne
 * veulent plus dire la même chose : 5'30" sur 15 km est une bien meilleure course que
 * 5'10" sur 3 km. Une courbe d'allure au fil des mois montre donc surtout **quelles
 * distances ont été courues**, tout en ayant l'air d'une progression.
 *
 * La page ne cache pas la courbe — elle la dit. Et elle pose à côté les trois lectures qui
 * ne souffrent pas du défaut : le record **par bande de distance**, le **volume mensuel**
 * (des kilomètres sont des kilomètres), et la **fenêtre glissante** qui compare cinq
 * sorties à cinq autres plutôt qu'une à une.
 *
 * ## Aucun calcul métier ici
 *
 * Records, moyennes pondérées, bandes, volumes, bornes d'axes : tout arrive calculé de
 * `progress.py`. Le seul `Math` de ce fichier porte sur une valeur absolue d'affichage.
 */

import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';

import {
  Badge,
  Card,
  Chart,
  Empty,
  LinkButton,
  PageHead,
  Rule,
  Stat,
  Table,
} from '@/components/ui';
import type { Column } from '@/components/ui';
import { activityApi, type Run, type RunProgress } from '@/features/activity/api';
import { ApiError } from '@/lib/api';
import { cx } from '@/lib/cx';
import { dayMonth, hoursMinutes, num, pace, plural, shortDate } from '@/lib/format';
import { keys } from '@/lib/query';

import styles from '../Activity.module.css';

/** En deçà, la fenêtre n'a rien bougé — et le dire vaut mieux qu'un signe sur du bruit. */
const STEADY_S_PER_KM = 2;

/**
 * `2026-08` en `août 26`.
 *
 * Mettre en forme n'est pas calculer : le serveur rend la clé triée, l'écran la rend
 * lisible. Le jour est fixé au 15 — un mois n'a pas de jour, et le 1er tomberait dans le
 * mois précédent sur un fuseau à l'ouest de Greenwich.
 */
function monthLabel(key: string): string {
  const [year, month] = key.split('-');
  const when = new Date(Number(year), Number(month) - 1, 15);
  return when.toLocaleDateString('fr-FR', { month: 'short', year: '2-digit' });
}

/**
 * Ce que la fenêtre glissante veut dire, en toutes lettres.
 *
 * Comme partout dans ce domaine, le signe se lit à l'envers : négatif est une **bonne**
 * nouvelle. Le montrer nu serait offrir la meilleure occasion de conclure l'inverse.
 */
function trend(seconds: number, size: number): { label: string; detail: string } {
  const window = `sur tes ${String(size)} dernières sorties contre les ${String(size)} d’avant`;
  if (Math.abs(seconds) < STEADY_S_PER_KM) {
    return { label: 'Allure stable', detail: window };
  }
  return seconds < 0
    ? { label: 'Tu accélères', detail: `gagnées au kilomètre ${window}` }
    : { label: 'Tu ralentis', detail: `perdues au kilomètre ${window}` };
}

/**
 * Les colonnes de la liste — **trois**, et le compte de paliers logé dans la première.
 *
 * Il a été une quatrième colonne. À 390 px elle tenait ; à 360 — ce que fait un petit
 * Android — l'en-tête se coupait à « PALIE », et l'on lisait un mot tronqué avant de
 * penser à tirer le tableau. Rien n'était perdu, le conteneur défile, mais c'est
 * exactement le défaut que la page Course a déjà corrigé sur sa colonne de cadence.
 *
 * Le compte rejoint donc la cellule de date, qui portait déjà l'étoile du record et avait
 * la place. Trois colonnes tiennent à 360 px sans que rien ne se coupe.
 */
function columns(data: RunProgress): Column<Run>[] {
  return [
    {
      key: 'date',
      header: 'Date',
      render: (run) => (
        // La ligne entière mène à la course : c'est la raison d'être de la page, et un
        // lien sur la seule date offrirait une cible de 60 px de large sur 44 de haut.
        <Link className={styles.runLink} to={`/activite/course/${String(run.id)}`}>
          {/* `dayMonth` et non `shortDate` : quatre colonnes et une date à dix caractères
              ne tiennent pas dans 390 px, et la colonne « Paliers » se coupait au premier
              mot — on lisait « PAL » avant de penser à tirer le tableau. L'année est dans
              le détail de la course, à un appui d'ici. */}
          {dayMonth(run.date)}
          {run.id === data.best_pace_index && <span className={styles.mark}>★</span>}
          {/* Ce que la course porte en plus : une sortie importée a ses paliers, une
              sortie saisie au clavier n'en a pas — et ce n'est pas un manque, c'est ce
              qu'elle est. Aucun badge plutôt qu'un « 0 » qui se lirait comme une mesure. */}
          {run.splits > 0 && <Badge tone="signal">{run.splits}</Badge>}
        </Link>
      ),
    },
    {
      key: 'distance',
      header: 'Distance',
      numeric: true,
      render: (run) => `${num(run.distance_km, 2)} km`,
    },
    {
      key: 'pace',
      header: 'Allure',
      numeric: true,
      render: (run) =>
        run.pace_min_km == null ? <span className={styles.empty}>—</span> : pace(run.pace_min_km),
    },
  ];
}

export function Runs() {
  const { data, isPending, error } = useQuery({
    queryKey: keys.activity.runProgress(),
    queryFn: () => activityApi.runProgress(),
  });

  const months = data?.months ?? [];
  const paced = data?.runs.filter((run) => run.pace_min_km != null) ?? [];
  // La liste arrive la plus récente d'abord ; une courbe se lit dans le sens du temps.
  const timeline = [...paced].reverse();

  return (
    <div className={cx('wrap', styles.screen)}>
      <PageHead
        eyebrow="Domaine Activité"
        title="Toutes tes courses"
        actions={
          <LinkButton variant="quiet" to="/activite">
            Retour à l’activité
          </LinkButton>
        }
      >
        {data && data.total_runs > 0
          ? `${String(data.total_runs)} ${plural(data.total_runs, 'sortie')} · ${num(data.total_distance_km, 1)} km parcourus`
          : 'Ce qui a été couru, et ce qui a changé entre les sorties.'}
      </PageHead>

      {error !== null ? (
        <Card>
          <Empty title="Courses indisponibles">
            {error instanceof ApiError ? error.message : 'Le serveur n’a pas répondu.'}
          </Empty>
        </Card>
      ) : isPending ? (
        <Card>
          <p className={styles.empty}>chargement…</p>
        </Card>
      ) : data.total_runs === 0 ? (
        <Card>
          {/* Aucune valeur inventée : un tiret et ce que coûte le prochain geste. */}
          <Empty title="Aucune course enregistrée">
            Importe une capture Apple depuis l’activité — le résumé et la liste « Splits » — ou
            saisis une course à la main. La progression apparaîtra dès la deuxième sortie.
          </Empty>
        </Card>
      ) : (
        <>
          <div className="grid tiles">
            <Card>
              <Stat compact label="Sorties" value={data.total_runs} />
            </Card>
            <Card>
              <Stat compact label="Distance" value={num(data.total_distance_km, 1)} unit="km" />
            </Card>
            <Card>
              <Stat compact label="Temps" value={hoursMinutes(data.total_minutes)} />
            </Card>
            <Card>
              <Stat
                compact
                label="Allure totale"
                value={data.overall_pace_min_km == null ? '—' : pace(data.overall_pace_min_km)}
                unit={data.overall_pace_min_km == null ? undefined : '/km'}
                detail="temps total ÷ distance totale"
              />
            </Card>
          </div>

          {/* ── Ce que la page existe pour montrer ───── */}
          {data.window.size > 0 && data.window.pace_delta_s_per_km != null && (
            <>
              <Rule>Ce qui a changé</Rule>
              <Card>
                <Stat
                  label={trend(data.window.pace_delta_s_per_km, data.window.size).label}
                  value={`${num(Math.abs(data.window.pace_delta_s_per_km), 1)} s/km`}
                  detail={trend(data.window.pace_delta_s_per_km, data.window.size).detail}
                  direction={data.window.pace_delta_s_per_km < 0 ? 'up' : 'down'}
                />
                <p className={styles.note}>
                  {data.window.previous_pace_min_km != null &&
                    data.window.recent_pace_min_km != null &&
                    `${pace(data.window.previous_pace_min_km)} puis ${pace(data.window.recent_pace_min_km)} au kilomètre. `}
                  Une fenêtre de {data.window.size} sorties plutôt qu’une course contre une course :
                  un fractionné isolé ferait sinon dire à la dernière séance que la forme s’est
                  effondrée. Les distances y restent mélangées.
                  {data.window.distance_delta_km != null &&
                    ` La sortie moyenne a ${data.window.distance_delta_km >= 0 ? 'gagné' : 'perdu'} ${num(Math.abs(data.window.distance_delta_km), 1)} km.`}
                </p>
              </Card>
            </>
          )}

          {/* ── Le volume, la seule série sans réserve ── */}
          {months.length >= 2 && (
            <Card>
              <h3>Kilomètres par mois</h3>
              <p className={styles.note}>
                La seule courbe de cette page qui se lise sans précaution : des kilomètres sont des
                kilomètres, et leur somme ne dépend pas des distances choisies. Un mois sans course
                est absent plutôt qu’à zéro — un trou est plus honnête qu’une mesure inventée.
              </p>
              <Chart
                labels={months.map((month) => monthLabel(month.month))}
                primary={{
                  label: 'Distance',
                  unit: 'km',
                  values: months.map((month) => month.distance_km),
                  tone: 'effort',
                  format: (value) => `${num(value, 1)} km`,
                  ...(data.volume_domain_km ? { domain: data.volume_domain_km } : {}),
                }}
                band={{
                  label: 'Sorties',
                  // Pas d'`unit` du tout : la légende écrit « label (unité) », et le
                  // couple donnait « Sorties (sorties) ». Le libellé porte déjà l'unité,
                  // et l'infobulle se lit très bien avec le nombre seul.
                  values: months.map((month) => month.runs),
                  tone: 'load',
                  format: (value) => String(value),
                }}
              />
            </Card>
          )}

          {/* ── Les records, là où ils veulent dire quelque chose ── */}
          <Rule>Tes meilleurs temps</Rule>
          <Card>
            <p className={styles.note}>
              Par bande de distance, et c’est la seule façon honnête de les comparer : 5’30” sur 15
              km est une meilleure course que 5’10” sur 3 km. Une bande jamais courue reste affichée
              — ne l’avoir jamais courue est une information.
            </p>
            <div className="grid tiles">
              {data.bands.map((band) => (
                <Card key={band.label}>
                  <Stat
                    compact
                    label={band.label}
                    value={band.best_pace_min_km == null ? '—' : pace(band.best_pace_min_km)}
                    unit={band.best_pace_min_km == null ? undefined : '/km'}
                    detail={
                      band.runs === 0
                        ? 'jamais couru'
                        : `${String(band.runs)} ${plural(band.runs, 'sortie')}${band.best_day == null ? '' : ` · record le ${shortDate(band.best_day)}`}`
                    }
                  />
                </Card>
              ))}
            </div>
          </Card>

          {/* ── La courbe qui porte la réserve ───────── */}
          {timeline.length >= 2 && (
            <Card>
              <h3>Allure sortie par sortie</h3>
              <p className={styles.note}>
                L’axe est inversé : plus le point est haut, plus la sortie a été rapide. Cette
                courbe mélange les distances — les barres du bas les rappellent, et un creux est
                souvent une sortie longue plutôt qu’un mauvais jour. Pour une comparaison qui tient,
                ce sont les records par bande, au-dessus.
              </p>
              <Chart
                labels={timeline.map((run) => shortDate(run.date))}
                primary={{
                  label: 'Allure',
                  unit: 'min/km',
                  values: timeline.map((run) => run.pace_min_km ?? 0),
                  tone: 'signal',
                  format: (value) => pace(value),
                  ...(data.pace_domain_min_km ? { domain: data.pace_domain_min_km } : {}),
                }}
                band={{
                  label: 'Distance',
                  unit: 'km',
                  values: timeline.map((run) => run.distance_km),
                  tone: 'load',
                  format: (value) => num(value, 1),
                }}
              />
            </Card>
          )}

          {/* ── La liste, qui est l'autre raison d'être de la page ── */}
          <Rule>
            {data.total_runs} {plural(data.total_runs, 'course')}
          </Rule>
          <Card>
            <p className={styles.note}>
              Chaque ligne mène au détail de sa course. Le badge dit combien de paliers elle porte :
              une sortie importée a les siens, une sortie saisie au clavier n’en a pas. L’étoile
              marque ta meilleure allure.
            </p>
            <Table
              columns={columns(data)}
              rows={data.runs}
              rowKey={(run) => String(run.id)}
              caption="Toutes les courses, la plus récente d’abord"
            />
          </Card>
        </>
      )}
    </div>
  );
}
