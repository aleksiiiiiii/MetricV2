/**
 * Écran Activité — courses et séances.
 *
 * **Ce qu'on fait passe devant ce qu'on lit.** L'écran était un tableau de bord auquel on
 * avait ajouté un formulaire : trois sections de statistiques, puis le journal, puis la
 * saisie, tout en bas, à 3 900 px du haut. Consigner une série entre deux exercices
 * demandait de traverser l'écran. C'est maintenant l'inverse — le journal en tête,
 * l'historique juste après, les statistiques derrière.
 *
 * Les sections vivent dans `routes/activity/`, comme `routes/settings/` l'a fait pour
 * Réglages. Ce fichier n'assemble plus que les états de l'écran et l'état partagé : la
 * séance ouverte, la feuille en cours, l'exercice qu'on vient de déclarer.
 */

import { useMutation, useQuery } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';

import { Badge, Bars, Button, Card, PageHead, Rule, Stat } from '@/components/ui';
import type { Tone } from '@/components/ui';
import { activityApi, type ActivityItem, type NeglectedGroup } from '@/features/activity/api';
import { useAiStatus } from '@/features/ai/useAiStatus';
import { ApiError } from '@/lib/api';
import { cx } from '@/lib/cx';
import { delta, hoursMinutes, num, pace, plural, shortDate } from '@/lib/format';
import { keys } from '@/lib/query';
import { useToast } from '@/lib/toast';

import styles from './Activity.module.css';
import { ActivitySheet, type SheetTarget } from './activity/ActivitySheet';
import { AppleImport } from './activity/AppleImport';
import { CatalogueSheet } from './activity/CatalogueSheet';
import { History } from './activity/History';
import { Journal } from './activity/Journal';
import { toSession, useInvalidateActivity, type Session } from './activity/shared';

const WEEKDAYS = ['lun', 'mar', 'mer', 'jeu', 'ven', 'sam', 'dim'];

/** Au-delà de deux semaines sans stimulus, le groupe décroche visiblement. */
const NEGLECT_ALERT_DAYS = 14;

function neglectTone(group: NeglectedGroup): Tone {
  if (group.days_since === null) return 'recover';
  if (group.days_since >= NEGLECT_ALERT_DAYS) return 'load';
  return 'effort';
}

export function Activity() {
  const invalidate = useInvalidateActivity();
  const { notify } = useToast();
  const ai = useAiStatus();

  const [picked, setPicked] = useState<Session | null>(null);
  const [sheet, setSheet] = useState<SheetTarget | null>(null);
  const [catalogue, setCatalogue] = useState(false);
  // L'exercice qu'on vient de déclarer depuis le journal : il se choisit dans la foulée,
  // sans avoir à le retrouver dans la grille.
  const [preselect, setPreselect] = useState<string | null>(null);

  // Choisir une séance depuis l'historique doit **se voir**. L'historique est sous le
  // journal : sans ce défilement, « ouvrir » après avoir descendu la page ne montrait
  // rien du tout.
  const logRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (picked === null) return;
    logRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' });
  }, [picked]);

  const { data, isPending } = useQuery({
    queryKey: keys.activity.overview(),
    queryFn: activityApi.overview,
  });
  const { data: progress } = useQuery({
    queryKey: keys.activity.progress(),
    queryFn: activityApi.progress,
  });

  const remove = useMutation({
    mutationFn: (item: ActivityItem) =>
      item.kind === 'run'
        ? activityApi.deleteRun(item.id, item.token)
        : activityApi.deleteWorkout(item.id, item.token),
    onSuccess: (_removed, item) => {
      // Le journal ne doit pas rester ouvert sur une séance qui n'existe plus : sans
      // cela il afficherait le refus du serveur au lieu de retomber sur la précédente.
      if (item.kind === 'workout' && picked?.id === item.id) setPicked(null);
      invalidate();
      notify('Activité supprimée.', 'signal');
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Suppression impossible.', 'recover');
      invalidate();
    },
  });

  const duplicate = useMutation({
    mutationFn: (item: ActivityItem) =>
      // Le jour vient du serveur, jamais de l'horloge du téléphone.
      activityApi.duplicateWorkout(item.id, data?.today ?? item.date),
    onSuccess: (workout) => {
      invalidate();
      setPicked(toSession(workout));
      notify('Séance dupliquée avec ses exercices.', 'effort');
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Duplication impossible.', 'recover');
    },
  });

  const week = data?.week;
  const today = data?.today;

  const sessions: Session[] = (data?.history ?? [])
    .filter((row) => row.kind === 'workout')
    .map((row) => ({ id: row.id, date: row.date, label: row.label }));

  // Une séance tout juste créée n'est pas encore dans l'historique relu : le temps d'un
  // aller-retour, le sélecteur afficherait la précédente pendant que le journal montre
  // déjà la nouvelle. On la place en tête jusqu'à ce que l'historique la rattrape.
  if (picked !== null && !sessions.some((item) => item.id === picked.id)) {
    sessions.unshift(picked);
  }

  const currentId = picked?.id ?? sessions[0]?.id ?? null;

  return (
    <div className={cx('wrap', styles.screen)}>
      <PageHead eyebrow="Domaine Activité" title={<>Courses &amp; séances</>} />

      <Rule>Séance</Rule>
      <div ref={logRef}>
        <Journal
          sessions={sessions}
          currentId={currentId}
          onPick={setPicked}
          preselect={preselect}
          ready={today !== undefined}
          onNew={(kind) => {
            setSheet({ kind, editing: null });
          }}
          onEditWorkout={(id) => {
            const session = sessions.find((item) => item.id === id);
            if (session === undefined) return;
            setSheet({
              kind: 'workout',
              editing: { kind: 'workout', id, date: session.date },
            });
          }}
          onMissingExercise={() => {
            setCatalogue(true);
          }}
        />
      </div>

      <Rule>Historique</Rule>
      <History
        data={data}
        isPending={isPending}
        removing={remove.isPending}
        onOpen={(row) => {
          // Choisir, pas charger. Le journal relit la séance lui-même et affiche en
          // place ce que le serveur refuse.
          setPicked({ id: row.id, date: row.date, label: row.label });
        }}
        onEdit={(row) => {
          const kind = row.kind === 'run' ? 'run' : 'workout';
          setSheet({ kind, editing: { kind, id: row.id, date: row.date } });
        }}
        onDuplicate={(row) => {
          duplicate.mutate(row);
        }}
        onRemove={(row) => {
          remove.mutate(row);
        }}
      />

      <Rule>Cette semaine</Rule>
      {/* Des tuiles : un libellé, un chiffre, une ligne. Empilées, il fallait faire
          défiler pour comparer deux nombres qui se lisent d'un même coup d'œil. */}
      <div className="grid tiles">
        <Card>
          <Stat
            compact
            label="Temps total"
            value={week ? hoursMinutes(week.minutes) : '—'}
            detail={week ? `${week.sessions} ${plural(week.sessions, 'séance')}` : 'chargement…'}
          />
        </Card>
        <Card>
          <Stat
            compact
            label="Distance"
            value={week && week.distance_km > 0 ? num(week.distance_km, 1) : '—'}
            unit={week && week.distance_km > 0 ? 'km' : undefined}
            detail={
              week?.pace_min_km != null ? `allure ${pace(week.pace_min_km)} /km` : 'aucune course'
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
              data
                ? num(
                    data.muscles.reduce((total, item) => total + item.volume_kg, 0),
                    0,
                  )
                : '—'
            }
            unit={data && data.muscles.length > 0 ? 'kg' : undefined}
            detail={
              data
                ? `${data.muscles.length} ${plural(data.muscles.length, 'groupe')} ${plural(data.muscles.length, 'travaillé')}`
                : undefined
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
          {(data?.days ?? []).map((day, index) => (
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
                {day.rest ? <span className={styles.empty}>repos</span> : hoursMinutes(day.minutes)}
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
            Charge × séries × réps. Les minutes ne distinguent pas trois séries de huit d'une heure
            de repos entre les séries.
          </p>
          {data && data.muscles.length > 0 ? (
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
            Jours depuis la dernière sollicitation. « Jamais » n'est pas « il y a longtemps » — les
            deux ne se traitent pas pareil.
          </p>
          <div className={styles.groups}>
            {(data?.neglected ?? []).map((group) => (
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

      <Rule>Catalogue et imports</Rule>
      <div className="stack">
        <Card>
          <h3>Catalogue d&apos;exercices</h3>
          <p className={styles.note}>
            À déclarer une fois : l&apos;exercice devient ensuite proposé dans le journal. Le
            retirer conserve tout l&apos;historique — les performances passées restent lisibles sans
            lui.
          </p>
          <div className={styles.spaced}>
            <Button
              variant="ghost"
              onClick={() => {
                setCatalogue(true);
              }}
            >
              Gérer le catalogue
            </Button>
          </div>
        </Card>

        {/* Même intention que le formulaire de séance, par une autre porte. Sans clé, la
            carte n'apparaît pas : un import qui ne peut pas lire n'a rien à proposer, et
            les deux formulaires manuels suffisent à tout (`IA-07`). L'état de
            l'assistance se lit dans Réglages. */}
        {ai.enabled && <AppleImport today={today} />}
      </div>

      {/* La feuille est remontée à chaque ouverture : ses champs repartent de la ligne
          visée, sans effet de bord d'une ouverture sur la suivante. */}
      {sheet !== null && today !== undefined && (
        <ActivitySheet
          key={`${sheet.kind}-${sheet.editing?.id ?? 'new'}`}
          target={sheet}
          today={today}
          onClose={() => {
            setSheet(null);
          }}
          onSaved={(workout) => {
            setSheet(null);
            if (workout !== null) setPicked(toSession(workout));
          }}
        />
      )}

      <CatalogueSheet
        open={catalogue}
        onClose={() => {
          setCatalogue(false);
        }}
        onCreated={(exercise) => {
          setPreselect(exercise.exercise_id);
          setCatalogue(false);
        }}
      />
    </div>
  );
}
