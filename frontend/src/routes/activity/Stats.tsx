/**
 * Les chiffres de l'activité, à leur adresse — `/activite/statistiques`.
 *
 * Ces quatre sections vivaient sous le journal, sur le même écran que lui : tonnage
 * hebdomadaire, volume par jour, équilibre des groupes, progression des charges. Tout
 * s'affichait en même temps, et `/activite` faisait plus de trois écrans de haut sur un
 * téléphone alors qu'on l'ouvre pour consigner une série entre deux exercices.
 *
 * Elles ont donc une page, et pour la même raison que le catalogue : une adresse, une
 * entrée d'historique, et un écran qu'on ouvre quand on vient lire — pas quand on vient
 * écrire. Rien n'a changé de ce qu'elles affichent.
 *
 * **Deux calculs métier y sont encore côté client** — la somme du tonnage et les deux
 * ratios tirés d'un `Math.max`. Ils sont arrivés ici tels quels : les corriger demande un
 * champ de plus au service backend, et ce n'était pas le périmètre du lot. Ils sont dans
 * les points ouverts de `CLAUDE.md`.
 */

import { useQuery } from '@tanstack/react-query';

import { Badge, Bars, Card, Empty, LinkButton, PageHead, Rule, Stat } from '@/components/ui';
import type { Tone } from '@/components/ui';
import { activityApi, type NeglectedGroup } from '@/features/activity/api';
import { ApiError } from '@/lib/api';
import { cx } from '@/lib/cx';
import { delta, hoursMinutes, num, pace, plural, shortDate } from '@/lib/format';
import { keys } from '@/lib/query';

import styles from '../Activity.module.css';

const WEEKDAYS = ['lun', 'mar', 'mer', 'jeu', 'ven', 'sam', 'dim'];

/** Au-delà de deux semaines sans stimulus, le groupe décroche visiblement. */
const NEGLECT_ALERT_DAYS = 14;

function neglectTone(group: NeglectedGroup): Tone {
  if (group.days_since === null) return 'recover';
  if (group.days_since >= NEGLECT_ALERT_DAYS) return 'load';
  return 'effort';
}

export function Stats() {
  // Mêmes clés que `/activite` : la requête est mutualisée par le cache, pas dupliquée.
  const { data, isPending, error } = useQuery({
    queryKey: keys.activity.overview(),
    queryFn: activityApi.overview,
  });
  const { data: progress } = useQuery({
    queryKey: keys.activity.progress(),
    queryFn: activityApi.progress,
  });

  const week = data?.week;
  const today = data?.today;

  return (
    <div className={cx('wrap', styles.screen)}>
      {/* L'en-tête est là **avant** la donnée : un écran qui n'affiche qu'un
          « chargement… » ne dit pas où l'on vient d'arriver. */}
      <PageHead
        eyebrow="Domaine Activité"
        title="Statistiques"
        actions={
          <LinkButton variant="quiet" to="/activite">
            Retour à l’activité
          </LinkButton>
        }
      >
        Ce que la semaine a produit, et ce qu’elle a laissé de côté.
      </PageHead>

      {error !== null ? (
        <Card>
          <Empty title="Statistiques indisponibles">
            {error instanceof ApiError ? error.message : 'Le serveur n’a pas répondu.'}
          </Empty>
        </Card>
      ) : isPending ? (
        <Card>
          <p className={styles.empty}>chargement…</p>
        </Card>
      ) : (
        <>
          <Rule>Cette semaine</Rule>
          {/* Des tuiles : un libellé, un chiffre, une ligne. Empilées, il fallait faire
              défiler pour comparer deux nombres qui se lisent d'un même coup d'œil. */}
          <div className="grid tiles">
            <Card>
              <Stat
                compact
                label="Temps total"
                value={week ? hoursMinutes(week.minutes) : '—'}
                detail={week ? `${week.sessions} ${plural(week.sessions, 'séance')}` : undefined}
              />
            </Card>
            <Card>
              <Stat
                compact
                label="Distance"
                value={week && week.distance_km > 0 ? num(week.distance_km, 1) : '—'}
                unit={week && week.distance_km > 0 ? 'km' : undefined}
                detail={
                  week?.pace_min_km != null
                    ? `allure ${pace(week.pace_min_km)} /km`
                    : 'aucune course'
                }
              />
            </Card>
            <Card>
              <Stat
                compact
                label="Séances"
                value={week ? String(week.sessions) : '—'}
                detail={week ? `semaine du ${shortDate(week.week_start)}` : undefined}
              />
            </Card>
            <Card>
              <Stat
                compact
                label="Tonnage"
                value={
                  data.muscles.length > 0
                    ? num(
                        data.muscles.reduce((total, item) => total + item.volume_kg, 0),
                        0,
                      )
                    : '—'
                }
                unit={data.muscles.length > 0 ? 'kg' : undefined}
                detail={
                  data.muscles.length > 0
                    ? `${data.muscles.length} ${plural(data.muscles.length, 'groupe')} ${plural(data.muscles.length, 'travaillé')}`
                    : 'aucune charge consignée'
                }
              />
            </Card>
          </div>

          <Card>
            <h3>Volume par jour</h3>
            <p className={styles.note}>
              Un jour de repos est un choix, pas un trou : il est tracé en pointillé et non à zéro.
            </p>
            <div className={styles.week}>
              {data.days.map((day, index) => (
                <div
                  className={cx(
                    styles.day,
                    day.rest && styles.dayRest,
                    day.date === today && styles.dayToday,
                  )}
                  key={day.date}
                >
                  <div className={styles.dayName}>{WEEKDAYS[index]}</div>
                  <div className={styles.dayValue}>
                    {day.rest ? (
                      <span className={styles.empty}>repos</span>
                    ) : (
                      hoursMinutes(day.minutes)
                    )}
                  </div>
                </div>
              ))}
            </div>
          </Card>

          <Rule>Charge et équilibre</Rule>
          <div className="grid g2">
            <Card>
              <h3>Tonnage par groupe</h3>
              <p className={styles.note}>
                Charge × séries × réps. Les minutes ne distinguent pas trois séries de huit d’une
                heure de repos entre les séries.
              </p>
              {data.muscles.length > 0 ? (
                <Bars
                  rows={data.muscles.map((item) => ({
                    label: item.muscle_group,
                    ratio: item.volume_kg / Math.max(...data.muscles.map((m) => m.volume_kg)),
                    value: `${num(item.volume_kg, 0)} kg`,
                    tone: 'effort',
                  }))}
                />
              ) : (
                <p className={cx(styles.empty, styles.emptyInset)}>
                  aucun exercice consigné cette semaine
                </p>
              )}
            </Card>

            <Card>
              <h3>Groupes négligés</h3>
              <p className={styles.note}>
                Jours depuis la dernière sollicitation. « Jamais » n’est pas « il y a longtemps » —
                les deux ne se traitent pas pareil.
              </p>
              <div className={styles.groups}>
                {data.neglected.map((group) => (
                  <Badge tone={neglectTone(group)} key={group.muscle_group}>
                    {group.muscle_group} ·{' '}
                    {group.days_since === null ? 'jamais' : `${group.days_since} j`}
                  </Badge>
                ))}
              </div>
            </Card>
          </div>

          {progress !== undefined && progress.length > 0 && (
            <>
              <Rule>Progression des charges</Rule>
              <Card>
                <Bars
                  rows={progress.map((item) => ({
                    label: item.name,
                    ratio:
                      (item.last_weight_kg ?? 0) /
                      Math.max(...progress.map((p) => p.best_weight_kg ?? 1)),
                    value:
                      item.delta_kg != null
                        ? `${num(item.last_weight_kg ?? 0, 1)} kg (${delta(item.delta_kg)})`
                        : `${num(item.last_weight_kg ?? 0, 1)} kg`,
                    tone: item.delta_kg != null && item.delta_kg > 0 ? 'effort' : 'signal',
                  }))}
                />
              </Card>
            </>
          )}
        </>
      )}
    </div>
  );
}
