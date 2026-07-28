import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import type { SyntheticEvent } from 'react';

import { Badge, Bars, Button, Card, Empty, Field, Rule, Stat, Table } from '@/components/ui';
import type { Column, Tone } from '@/components/ui';
import {
  activityApi,
  type ActivityItem,
  type ExerciseEntryPayload,
  type NeglectedGroup,
  type Workout,
} from '@/features/activity/api';
import { ApiError } from '@/lib/api';
import { cx } from '@/lib/cx';
import { delta, duration, hoursMinutes, isoDay, km, num, pace, shortDate } from '@/lib/format';
import { CROSS_CUTTING, keys } from '@/lib/query';
import { useToast } from '@/lib/toast';

import styles from './Activity.module.css';

const WEEKDAYS = ['lun', 'mar', 'mer', 'jeu', 'ven', 'sam', 'dim'];

/** Au-delà de deux semaines sans stimulus, le groupe décroche visiblement. */
const NEGLECT_ALERT_DAYS = 14;

function useInvalidateActivity() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: keys.activity.all() });
    for (const key of CROSS_CUTTING) void client.invalidateQueries({ queryKey: key });
  };
}

function neglectTone(group: NeglectedGroup): Tone {
  if (group.days_since === null) return 'recover';
  if (group.days_since >= NEGLECT_ALERT_DAYS) return 'load';
  return 'effort';
}

// ── Saisie d'une course ───────────────────────────────

function RunForm() {
  const invalidate = useInvalidateActivity();
  const { notify } = useToast();
  const [fields, setFields] = useState({
    date: isoDay(new Date()),
    distance_km: '',
    duration_min: '',
    avg_hr: '',
    note: '',
  });
  const [error, setError] = useState<ApiError | null>(null);

  const save = useMutation({
    mutationFn: () =>
      activityApi.createRun({
        date: fields.date,
        distance_km: fields.distance_km,
        duration_min: fields.duration_min,
        avg_hr: fields.avg_hr || null,
        note: fields.note || null,
      }),
    onSuccess: (run) => {
      invalidate();
      notify(
        `Course enregistrée — ${km(run.distance_km)} en ${duration(run.duration_min)}.`,
        'effort',
      );
      setFields((current) => ({
        ...current,
        distance_km: '',
        duration_min: '',
        avg_hr: '',
        note: '',
      }));
      setError(null);
    },
    onError: (caught: unknown) => {
      setError(caught instanceof ApiError ? caught : null);
    },
  });

  const set = (name: keyof typeof fields) => (event: { target: { value: string } }) => {
    setFields((current) => ({ ...current, [name]: event.target.value }));
  };

  function submit(event: SyntheticEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <form className={styles.form} onSubmit={submit} noValidate>
      {error !== null && (
        <p className={styles.error} role="alert">
          {error.message}
        </p>
      )}

      <div className={styles.pair}>
        <Field
          label="Date"
          type="date"
          value={fields.date}
          max={isoDay(new Date())}
          onChange={set('date')}
        />
        <Field
          label="Distance"
          placeholder="8,40 ou 5mi"
          value={fields.distance_km}
          error={error?.messageFor('distance_km')}
          onChange={set('distance_km')}
        />
      </div>

      <div className={styles.pair}>
        <Field
          label="Durée"
          placeholder="44:12 ou 1h30"
          hint="mm:ss, h:mm:ss ou minutes"
          value={fields.duration_min}
          error={error?.messageFor('duration_min')}
          onChange={set('duration_min')}
        />
        <Field
          label="FC moyenne"
          inputMode="numeric"
          placeholder="152"
          value={fields.avg_hr}
          error={error?.messageFor('avg_hr')}
          onChange={set('avg_hr')}
        />
      </div>

      <Field
        label="Ressenti"
        placeholder="jambes lourdes, vent de face…"
        value={fields.note}
        onChange={set('note')}
      />

      <Button
        type="submit"
        variant="primary"
        busy={save.isPending}
        disabled={fields.distance_km === '' || fields.duration_min === ''}
      >
        Enregistrer la course
      </Button>
    </form>
  );
}

// ── Saisie d'une séance ───────────────────────────────

function WorkoutForm({ onCreated }: { onCreated: (workout: Workout) => void }) {
  const invalidate = useInvalidateActivity();
  const { notify } = useToast();
  const { data: types } = useQuery({ queryKey: keys.activity.types(), queryFn: activityApi.types });

  const [fields, setFields] = useState({
    date: isoDay(new Date()),
    type: 'musculation',
    duration_min: '',
    rpe: '',
    note: '',
  });
  const [error, setError] = useState<ApiError | null>(null);

  const save = useMutation({
    mutationFn: () =>
      activityApi.createWorkout({
        date: fields.date,
        type: fields.type,
        duration_min: fields.duration_min,
        rpe: fields.rpe ? Number(fields.rpe) : null,
        note: fields.note || null,
      }),
    onSuccess: (workout) => {
      invalidate();
      notify('Séance enregistrée. Ajoute tes exercices.', 'effort');
      setFields((current) => ({ ...current, duration_min: '', rpe: '', note: '' }));
      setError(null);
      onCreated(workout);
    },
    onError: (caught: unknown) => {
      setError(caught instanceof ApiError ? caught : null);
    },
  });

  const set = (name: keyof typeof fields) => (event: { target: { value: string } }) => {
    setFields((current) => ({ ...current, [name]: event.target.value }));
  };

  return (
    <form
      className={styles.form}
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate();
      }}
      noValidate
    >
      {error !== null && (
        <p className={styles.error} role="alert">
          {error.message}
        </p>
      )}

      <div className={styles.pair}>
        <Field
          label="Date de séance"
          type="date"
          value={fields.date}
          max={isoDay(new Date())}
          onChange={set('date')}
        />
        <div className={styles.field}>
          <label htmlFor="workout-type">Type</label>
          {/* Liste libre : les sept types sont des suggestions (`ACT-03`). */}
          <input
            id="workout-type"
            className={styles.select}
            list="workout-types"
            value={fields.type}
            onChange={set('type')}
          />
          <datalist id="workout-types">
            {(types ?? []).map((type) => (
              <option value={type} key={type} />
            ))}
          </datalist>
        </div>
      </div>

      <div className={styles.pair}>
        <Field
          label="Durée de séance"
          placeholder="1h15"
          value={fields.duration_min}
          error={error?.messageFor('duration_min')}
          onChange={set('duration_min')}
        />
        <Field
          label="Effort perçu (1–10)"
          inputMode="numeric"
          placeholder="8"
          value={fields.rpe}
          error={error?.messageFor('rpe')}
          onChange={set('rpe')}
        />
      </div>

      <Field
        label="Note"
        placeholder="contenu de la séance…"
        value={fields.note}
        onChange={set('note')}
      />

      <Button
        type="submit"
        variant="primary"
        busy={save.isPending}
        disabled={fields.duration_min === ''}
      >
        Enregistrer la séance
      </Button>
    </form>
  );
}

// ── Journal d'exercices ───────────────────────────────

function ExerciseLog({ workout, onClose }: { workout: Workout; onClose: () => void }) {
  const invalidate = useInvalidateActivity();
  const { notify } = useToast();
  const { data: catalogue } = useQuery({
    queryKey: keys.activity.exercises(),
    queryFn: activityApi.exercises,
  });

  const [entry, setEntry] = useState<ExerciseEntryPayload>({
    exercise_id: '',
    weight_kg: '',
    sets: 3,
    reps: 8,
  });
  const [error, setError] = useState<ApiError | null>(null);

  const { data: detail } = useQuery({
    queryKey: keys.activity.workout(workout.id),
    queryFn: () => activityApi.readWorkout(workout.id),
    initialData: workout,
  });

  // Une réponse partielle ne doit pas produire un écran blanc.
  const entries = detail.exercises ?? [];

  const selected = (catalogue ?? []).find((item) => item.exercise_id === entry.exercise_id);

  const log = useMutation({
    mutationFn: () => activityApi.logExercise(workout.id, entry),
    onSuccess: () => {
      invalidate();
      notify('Performance consignée.', 'effort');
      setEntry((current) => ({ ...current, weight_kg: '' }));
      setError(null);
    },
    onError: (caught: unknown) => {
      setError(caught instanceof ApiError ? caught : null);
    },
  });

  return (
    <Card>
      <div className="spread">
        <div>
          <h3>Journal — {detail.type}</h3>
          <p className={styles.note}>
            {shortDate(detail.date)} · {hoursMinutes(detail.duration_min)}
            {detail.volume_kg > 0 && ` · ${num(detail.volume_kg, 0)} kg de tonnage`}
          </p>
        </div>
        <div className="row">
          {detail.rpe !== null && <Badge tone="load">RPE {detail.rpe}</Badge>}
          <button
            type="button"
            className={styles.iconButton}
            aria-label="Fermer le journal de cette séance"
            onClick={onClose}
          >
            fermer
          </button>
        </div>
      </div>

      {entries.length > 0 && (
        <div className={styles.entries}>
          {entries.map((item) => (
            <div className={styles.entry} key={item.id}>
              <span>
                {item.exercise_name}
                <span className={styles.entryDetail}> · {item.muscle_group}</span>
              </span>
              <span className={styles.entryDetail}>
                {item.weight_kg === 0 ? 'poids du corps' : `${num(item.weight_kg, 1)} kg`} ·{' '}
                {item.sets}×{item.reps}
                {item.one_rep_max_kg !== null && ` · 1RM ${num(item.one_rep_max_kg, 0)}`}
              </span>
            </div>
          ))}
        </div>
      )}

      <form
        className={styles.form}
        onSubmit={(event) => {
          event.preventDefault();
          log.mutate();
        }}
        noValidate
      >
        {error !== null && (
          <p className={styles.error} role="alert">
            {error.message}
          </p>
        )}

        <div className={styles.field}>
          <label htmlFor="exercise-pick">Exercice</label>
          <select
            id="exercise-pick"
            className={styles.select}
            value={entry.exercise_id}
            onChange={(event) => {
              setEntry((current) => ({ ...current, exercise_id: event.target.value }));
            }}
          >
            <option value="">— choisir —</option>
            {(catalogue ?? []).map((item) => (
              <option value={item.exercise_id} key={item.exercise_id}>
                {item.name} ({item.muscle_group})
              </option>
            ))}
          </select>
          {/* `ACT-08` : choisir sa charge sans consulter l'historique. */}
          {selected?.last_weight_kg != null && (
            <span className={styles.empty}>
              dernière fois : {num(selected.last_weight_kg, 1)} kg · {selected.last_sets}×
              {selected.last_reps}
            </span>
          )}
        </div>

        <div className={styles.triple}>
          <Field
            label="Charge (kg)"
            inputMode="decimal"
            placeholder="0 = poids du corps"
            value={entry.weight_kg}
            error={error?.messageFor('weight_kg')}
            onChange={(event) => {
              setEntry((current) => ({ ...current, weight_kg: event.target.value }));
            }}
          />
          <Field
            label="Séries"
            inputMode="numeric"
            value={String(entry.sets)}
            onChange={(event) => {
              setEntry((current) => ({ ...current, sets: Number(event.target.value) || 1 }));
            }}
          />
          <Field
            label="Réps"
            inputMode="numeric"
            value={String(entry.reps)}
            onChange={(event) => {
              setEntry((current) => ({ ...current, reps: Number(event.target.value) || 1 }));
            }}
          />
        </div>

        <Button
          type="submit"
          variant="ghost"
          busy={log.isPending}
          disabled={entry.exercise_id === ''}
        >
          Consigner
        </Button>
      </form>
    </Card>
  );
}

// ── Catalogue ─────────────────────────────────────────

function ExerciseCatalogue() {
  const invalidate = useInvalidateActivity();
  const { notify } = useToast();
  const { data: groups } = useQuery({
    queryKey: keys.activity.muscleGroups(),
    queryFn: activityApi.muscleGroups,
  });

  const [name, setName] = useState('');
  const [group, setGroup] = useState('pectoraux');

  const create = useMutation({
    mutationFn: () => activityApi.createExercise(name, group),
    onSuccess: () => {
      invalidate();
      notify('Exercice ajouté au catalogue.', 'signal');
      setName('');
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Ajout impossible.', 'recover');
    },
  });

  return (
    <Card>
      <h3>Catalogue d'exercices</h3>
      <p className={styles.note}>
        Retirer un exercice conserve tout l'historique : les performances passées restent lisibles
        sans lui.
      </p>
      <form
        className={styles.form}
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate();
        }}
        noValidate
      >
        <Field
          label="Nom"
          placeholder="Développé couché"
          value={name}
          onChange={(event) => {
            setName(event.target.value);
          }}
        />
        <div className={styles.field}>
          <label htmlFor="muscle-group">Groupe musculaire</label>
          <select
            id="muscle-group"
            className={styles.select}
            value={group}
            onChange={(event) => {
              setGroup(event.target.value);
            }}
          >
            {(groups ?? []).map((item) => (
              <option value={item} key={item}>
                {item}
              </option>
            ))}
          </select>
        </div>
        <Button type="submit" variant="ghost" busy={create.isPending} disabled={name.trim() === ''}>
          Ajouter au catalogue
        </Button>
      </form>
    </Card>
  );
}

// ── Écran ─────────────────────────────────────────────

export function Activity() {
  const invalidate = useInvalidateActivity();
  const { notify } = useToast();
  const [active, setActive] = useState<Workout | null>(null);

  // Ouvrir une séance depuis l'historique doit **se voir**. Le tableau est à gauche, le
  // journal à droite : sans ce défilement, ouvrir une séance après avoir descendu la
  // page ne montrait rien du tout.
  const logRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (active === null) return;
    logRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' });
  }, [active]);

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
    onSuccess: () => {
      invalidate();
      notify('Activité supprimée.', 'signal');
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Suppression impossible.', 'recover');
      invalidate();
    },
  });

  const duplicate = useMutation({
    mutationFn: (item: ActivityItem) => activityApi.duplicateWorkout(item.id, isoDay(new Date())),
    onSuccess: (workout) => {
      invalidate();
      setActive(workout);
      notify('Séance dupliquée avec ses exercices.', 'effort');
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Duplication impossible.', 'recover');
    },
  });

  const columns: Column<ActivityItem>[] = [
    { key: 'date', header: 'Date', numeric: true, render: (row) => shortDate(row.date) },
    {
      key: 'label',
      header: 'Type',
      render: (row) => (
        <>
          {row.label}
          {row.kind === 'run' && <span className={styles.entryDetail}> · course</span>}
        </>
      ),
    },
    {
      key: 'distance',
      header: 'Dist.',
      numeric: true,
      render: (row) =>
        row.distance_km !== null ? km(row.distance_km) : <span className={styles.empty}>—</span>,
    },
    {
      key: 'duration',
      header: 'Durée',
      numeric: true,
      render: (row) => duration(row.duration_min),
    },
    {
      key: 'pace',
      header: 'Allure',
      numeric: true,
      render: (row) =>
        row.pace_min_km !== null ? pace(row.pace_min_km) : <span className={styles.empty}>—</span>,
    },
    {
      key: 'actions',
      header: '',
      render: (row) => (
        <div className={styles.actions}>
          {row.kind === 'workout' && (
            <>
              <button
                type="button"
                className={styles.iconButton}
                aria-label={`Ouvrir la séance du ${shortDate(row.date)}`}
                onClick={() => {
                  // Le `.catch` n'est pas décoratif : sans lui, un refus du serveur était
                  // avalé en silence et le bouton semblait simplement ne rien faire.
                  activityApi
                    .readWorkout(row.id)
                    .then(setActive)
                    .catch((caught: unknown) => {
                      notify(
                        caught instanceof ApiError ? caught.message : 'Séance introuvable.',
                        'recover',
                      );
                    });
                }}
              >
                ouvrir
              </button>
              <button
                type="button"
                className={styles.iconButton}
                aria-label={`Dupliquer la séance du ${shortDate(row.date)}`}
                onClick={() => {
                  duplicate.mutate(row);
                }}
              >
                dupliquer
              </button>
            </>
          )}
          <button
            type="button"
            className={cx(styles.iconButton, styles.danger)}
            aria-label={`Supprimer l'activité du ${shortDate(row.date)}`}
            onClick={() => {
              remove.mutate(row);
            }}
          >
            supprimer
          </button>
        </div>
      ),
    },
  ];

  const week = data?.week;
  const today = isoDay(new Date());

  return (
    <div className="wrap">
      <p className="eyebrow">Domaine Activité</p>
      <h1 style={{ marginTop: 10 }}>Courses &amp; séances</h1>

      <Rule>Cette semaine</Rule>
      <div className="grid g4">
        <Card>
          <Stat
            label="Temps total"
            value={week ? hoursMinutes(week.minutes) : '—'}
            detail={week ? `${week.sessions} séance(s)` : 'chargement…'}
          />
        </Card>
        <Card>
          <Stat
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
            label="Séances"
            value={week ? String(week.sessions) : '—'}
            detail={week ? `semaine du ${shortDate(week.week_start)}` : undefined}
          />
        </Card>
        <Card>
          <Stat
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
            detail={data ? `${data.muscles.length} groupe(s) travaillé(s)` : undefined}
          />
        </Card>
      </div>

      <Card className="mt">
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
            <p className={styles.empty} style={{ marginTop: 12 }}>
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

      <Rule>Saisie</Rule>
      <div className={styles.split}>
        <Card flush>
          <h3 style={{ padding: '0 12px 14px' }}>
            Historique {data !== undefined && <span className={styles.empty}>· {data.total}</span>}
          </h3>
          {isPending ? (
            <p className={styles.empty} style={{ padding: '0 12px 12px' }}>
              chargement…
            </p>
          ) : data && data.history.length > 0 ? (
            <Table
              columns={columns}
              rows={data.history}
              rowKey={(row) => `${row.kind}-${row.id}-${row.token}`}
              caption="Historique des activités"
            />
          ) : (
            <div style={{ padding: '0 12px 12px' }}>
              <Empty title="Aucune activité">
                Une sortie, une séance — la semaine commence à compter.
              </Empty>
            </div>
          )}
        </Card>

        <div className="stack">
          {/* En **tête** de colonne, et non entre deux formulaires : le bouton « ouvrir »
              vit dans le tableau de gauche, et un panneau qui s'insérait au milieu de la
              colonne de droite apparaissait hors du champ de vision. Cliquer semblait
              alors ne rien faire. */}
          {active !== null && (
            <div ref={logRef}>
              <ExerciseLog
                workout={active}
                onClose={() => {
                  setActive(null);
                }}
              />
            </div>
          )}

          <Card>
            <h3>Nouvelle course</h3>
            <RunForm />
          </Card>

          <Card>
            <h3>Nouvelle séance</h3>
            <WorkoutForm onCreated={setActive} />
          </Card>

          <ExerciseCatalogue />
        </div>
      </div>

      <div style={{ height: 40 }} />
    </div>
  );
}
