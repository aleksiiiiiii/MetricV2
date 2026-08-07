import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import type { SyntheticEvent } from 'react';

import {
  AiBlock,
  Badge,
  Bars,
  Button,
  Card,
  CardHead,
  Chip,
  ChipStrip,
  Empty,
  Field,
  LogButton,
  PageHead,
  Rule,
  Segmented,
  Stat,
  Stepper,
  SwipeRow,
} from '@/components/ui';
import type { Tone } from '@/components/ui';
import {
  activityApi,
  type ActivityItem,
  type ExerciseEntryPayload,
  type NeglectedGroup,
  type Workout,
} from '@/features/activity/api';
import { useAiStatus } from '@/features/ai/useAiStatus';
import { importsApi, type AppleDraft } from '@/features/imports/api';
import { ApiError } from '@/lib/api';
import { cx } from '@/lib/cx';
import {
  delta,
  duration,
  hoursMinutes,
  isoDay,
  km,
  num,
  pace,
  plural,
  shortDate,
} from '@/lib/format';
import { CROSS_CUTTING, keys } from '@/lib/query';
import { useHorizontalSwipe } from '@/lib/swipe';
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

// ── Journal de séance ─────────────────────────────────

/** Ce qu'il faut d'une séance pour la proposer au choix, sans avoir à la relire. */
interface Session {
  id: number;
  date: string;
  label: string;
}

function toSession(workout: Workout): Session {
  return { id: workout.id, date: workout.date, label: workout.type };
}

/**
 * Écrit un nombre pour le champ *et* pour le serveur.
 *
 * Volontairement sans séparateur de milliers, contrairement à `num` : ce texte part dans
 * la charge utile, et `1 000` y serait une valeur que le serveur devrait deviner. La
 * virgule, elle, fait partie du contrat `ACT-01`.
 */
function kgText(value: number): string {
  return String(Math.round(value * 100) / 100).replace('.', ',');
}

/** Contenu du journal : ce qui est déjà consigné, et de quoi consigner la suite. */
function SessionLog({ workoutId }: { workoutId: number }) {
  const invalidate = useInvalidateActivity();
  const { notify } = useToast();
  const { data: catalogue } = useQuery({
    queryKey: keys.activity.exercises(),
    queryFn: activityApi.exercises,
  });
  // Même clé que l'écran : la requête est mutualisée, pas dupliquée.
  const { data: progress } = useQuery({
    queryKey: keys.activity.progress(),
    queryFn: activityApi.progress,
  });

  // Séries et réps restent du **texte** tant qu'on saisit : les convertir à chaque frappe
  // ramenait le champ à 1 dès qu'on l'effaçait pour retaper.
  const [form, setForm] = useState({
    exercise_id: '',
    weight_kg: '',
    sets: '3',
    reps: '8',
  });
  const [error, setError] = useState<ApiError | null>(null);

  const set = (name: keyof typeof form) => (value: string) => {
    setForm((current) => ({ ...current, [name]: value }));
  };

  // La séance est relue **ici**. Un refus du serveur s'affiche donc à la place du
  // journal, là où le regard est déjà : porté par un toast depuis le bouton « ouvrir »,
  // il passait avant d'avoir été lu — quand il n'était pas simplement avalé.
  const {
    data: detail,
    isPending,
    error: unreadable,
  } = useQuery({
    queryKey: keys.activity.workout(workoutId),
    queryFn: () => activityApi.readWorkout(workoutId),
  });

  const log = useMutation({
    mutationFn: () => {
      const payload: ExerciseEntryPayload = {
        exercise_id: form.exercise_id,
        weight_kg: form.weight_kg,
        sets: Number(form.sets.replace(',', '.')) || 1,
        reps: Number(form.reps.replace(',', '.')) || 1,
      };
      return activityApi.logExercise(workoutId, payload);
    },
    onSuccess: () => {
      invalidate();
      notify('Performance consignée.', 'effort');
      setForm((current) => ({ ...current, weight_kg: '' }));
      setError(null);
    },
    onError: (caught: unknown) => {
      setError(caught instanceof ApiError ? caught : null);
    },
  });

  if (unreadable !== null) {
    return (
      <p className={cx(styles.error, styles.spaced)} role="alert">
        {unreadable instanceof ApiError ? unreadable.message : 'Séance illisible.'}
      </p>
    );
  }

  if (isPending) {
    return <p className={cx(styles.empty, styles.spaced)}>chargement…</p>;
  }

  // Une réponse partielle ne doit pas produire un écran blanc.
  const entries = detail.exercises ?? [];
  const selected = (catalogue ?? []).find((item) => item.exercise_id === form.exercise_id);
  const empty = catalogue !== undefined && catalogue.length === 0;

  // Charges rapides : les dernières valeurs **réellement soulevées**, telles que le
  // serveur les a calculées (`max_series`). Aucune n'est suggérée par arrondi ni par
  // progression supposée — une pastille propose ce qui a existé, pas ce qui devrait.
  const history = progress?.find((item) => item.exercise_id === form.exercise_id);
  const quick = [...new Set(history?.max_series ?? [])].slice(-3).reverse();

  return (
    <>
      <div className={styles.meta}>
        {/* Pas de date ici : le sélecteur juste au-dessus la porte déjà, et la lire
            deux fois de suite ne dit rien de plus. Cette ligne le complète. */}
        <p className={styles.note}>
          {hoursMinutes(detail.duration_min)}
          {detail.volume_kg > 0 && ` · ${num(detail.volume_kg, 0)} kg de tonnage`}
        </p>
        {detail.rpe !== null && <Badge tone="load">RPE {detail.rpe}</Badge>}
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

        {/* Sélection rapide : un appui par exercice, avec sa dernière charge en regard.
            La liste déroulante native demandait un appui, un panneau système, un
            défilement et un second appui — pour le geste le plus répété de l'écran. */}
        <div className={styles.pickField}>
          <span className={styles.pickLabel} id="exercise-label">
            Exercice
          </span>
          {empty ? (
            <span className={styles.empty}>
              catalogue vide — déclare un exercice pour pouvoir consigner une charge
            </span>
          ) : (
            <div className={styles.pickGrid} role="group" aria-labelledby="exercise-label">
              {(catalogue ?? []).map((item) => (
                <LogButton
                  key={item.exercise_id}
                  label={item.name}
                  // « 0 kg » se lirait comme une mesure manquante. Le reste de l'écran
                  // dit « poids du corps » ; il n'y a pas de raison d'un second mot ici.
                  hint={
                    item.last_weight_kg == null
                      ? item.muscle_group
                      : item.last_weight_kg === 0
                        ? 'poids du corps'
                        : `${num(item.last_weight_kg, 1)} kg`
                  }
                  aria-pressed={form.exercise_id === item.exercise_id}
                  className={cx(form.exercise_id === item.exercise_id && styles.pickOn)}
                  onClick={() => {
                    set('exercise_id')(item.exercise_id);
                  }}
                />
              ))}
            </div>
          )}
        </div>

        {/* `ACT-08` : choisir sa charge sans consulter l'historique. */}
        {selected?.last_weight_kg != null && (
          <span className={styles.empty}>
            dernière fois : {num(selected.last_weight_kg, 1)} kg · {selected.last_sets}×
            {selected.last_reps}
          </span>
        )}

        {quick.length > 0 && (
          <ChipStrip label="Charges récentes">
            {quick.map((weight) => (
              <Chip
                key={weight}
                selected={form.weight_kg === kgText(weight)}
                onClick={() => {
                  set('weight_kg')(kgText(weight));
                }}
              >
                {num(weight, 1)} kg
              </Chip>
            ))}
          </ChipStrip>
        )}

        <div className={styles.logGrid}>
          <Stepper
            label="Charge (kg)"
            value={form.weight_kg}
            onChange={set('weight_kg')}
            // 2,5 kg est le plus petit disque de la plupart des salles : c'est le pas
            // réel d'une progression, pas un pas décidé à la calculette.
            step={2.5}
            min={0}
            placeholder="0 = poids du corps"
            error={error?.messageFor('weight_kg')}
          />
          <Stepper
            label="Séries"
            inputMode="numeric"
            value={form.sets}
            onChange={set('sets')}
            min={1}
            max={20}
          />
          <Stepper
            label="Réps"
            inputMode="numeric"
            value={form.reps}
            onChange={set('reps')}
            min={1}
            max={50}
          />
        </div>

        <Button
          type="submit"
          variant="primary"
          className={styles.commit}
          busy={log.isPending}
          disabled={form.exercise_id === ''}
        >
          Consigner
        </Button>
      </form>
    </>
  );
}

/**
 * Le parcours principal de l'écran, et il est **toujours affiché**.
 *
 * Il n'existait auparavant que pendant qu'une séance était ouverte depuis l'historique.
 * Un écran qui n'ouvre rien de lui-même laissait donc le regard tomber sur le catalogue
 * d'exercices — le seul formulaire visible d'emblée, et le seul qui ne prend aucun
 * chiffre. L'ordre affiché contredisait l'ordre réel du geste.
 *
 * Le sélecteur remplace ce panneau conditionnel : la séance la plus récente est ouverte
 * d'office, les autres restent à un choix dans la liste.
 */
function WorkoutJournal({
  sessions,
  currentId,
  onPick,
}: {
  sessions: Session[];
  currentId: number | null;
  onPick: (session: Session) => void;
}) {
  // Balayer le journal passe d'une séance à l'autre. L'ordre est celui de la bande —
  // vers la gauche on remonte le temps, vers la droite on revient au récent.
  const rank = sessions.findIndex((item) => item.id === currentId);
  const swipe = useHorizontalSwipe({
    touchOnly: true,
    onLeft: () => {
      const older = sessions[rank + 1];
      if (older !== undefined) onPick(older);
    },
    onRight: () => {
      const newer = sessions[rank - 1];
      if (newer !== undefined) onPick(newer);
    },
  });

  return (
    <Card>
      <CardHead>
        <div>
          <h3>Journal de séance</h3>
          {/* La promesse ne vaut que s'il y a une séance à ouvrir : l'annoncer quand il
              n'y en a aucune décrirait un écran que l'utilisateur n'a pas sous les yeux. */}
          <p className={styles.note}>
            Les charges se consignent ici.
            {currentId !== null && ' La séance la plus récente est ouverte d’office.'}
          </p>
        </div>
      </CardHead>

      {currentId === null ? (
        <div className={styles.spaced}>
          <Empty title="Aucune séance">
            Enregistre une séance — sa date et sa durée suffisent. Ses exercices et leurs charges se
            consignent ensuite ici, un par un.
          </Empty>
        </div>
      ) : (
        <>
          <ChipStrip label="Séance">
            {sessions.map((item) => (
              <Chip
                key={item.id}
                selected={item.id === currentId}
                onClick={() => {
                  onPick(item);
                }}
              >
                {shortDate(item.date)} · {item.label}
              </Chip>
            ))}
          </ChipStrip>

          {/* Remonter le journal à chaque changement de séance : une charge tapée pour
              l'une ne doit pas se retrouver pré-remplie sur l'autre. */}
          <div className={styles.swipeArea} {...swipe.handlers}>
            <SessionLog workoutId={currentId} key={currentId} />
          </div>
        </>
      )}
    </Card>
  );
}

// ── Import Apple ──────────────────────────────────────

/** Les champs corrigeables d'un import. Tout reste du texte jusqu'au serveur (`ACT-01`). */
interface ImportFields {
  kind: 'run' | 'workout';
  date: string;
  type: string;
  distance_km: string;
  duration_min: string;
  avg_hr: string;
  elevation_m: string;
  calories: string;
}

const EMPTY_IMPORT: ImportFields = {
  kind: 'workout',
  date: '',
  type: '',
  distance_km: '',
  duration_min: '',
  avg_hr: '',
  elevation_m: '',
  calories: '',
};

/** Noms lisibles des champs qu'une capture peut ne pas porter (`IMP-03`). */
const FIELD_NAMES: Record<string, string> = {
  date: 'la date',
  distance_km: 'la distance',
  duration_min: 'la durée',
  avg_hr: 'la FC moyenne',
  elevation_m: 'le dénivelé',
  calories: 'les calories',
};

function numberText(value: number | null): string {
  return value === null ? '' : String(value).replace('.', ',');
}

/**
 * Import d'une capture Apple Fitness (`IMP-01` → `IMP-06`).
 *
 * Trois états successifs, et la frontière entre les deux derniers est le contrat du lot :
 * choisir une capture, la faire **lire**, puis — après correction — l'**écrire**. Rien ne
 * passe de la deuxième à la troisième sans un appui.
 *
 * Le pré-remplissage n'est pas un formulaire en lecture seule qu'on validerait en bloc :
 * chaque valeur est un pas-à-pas, corrigeable au pouce (`IMP-02`). Une valeur qu'on ne
 * peut pas retoucher est une valeur qu'on adopte faute de mieux.
 */
function AppleImport() {
  const invalidate = useInvalidateActivity();
  const { notify } = useToast();
  const fileInput = useRef<HTMLInputElement>(null);

  const [preview, setPreview] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [draft, setDraft] = useState<AppleDraft | null>(null);
  const [fields, setFields] = useState<ImportFields>(EMPTY_IMPORT);
  // Ce qui vient de la capture et n'a pas encore été retouché.
  const [proposed, setProposed] = useState<string[]>([]);
  const [error, setError] = useState<ApiError | null>(null);

  function reset() {
    setDraft(null);
    setFields(EMPTY_IMPORT);
    setProposed([]);
    setError(null);
  }

  function choose(chosen: File | null) {
    setPreview((current) => {
      if (current) URL.revokeObjectURL(current);
      return chosen ? URL.createObjectURL(chosen) : null;
    });
    setFile(chosen);
    // Un brouillon appartient à la capture qui l'a produit.
    reset();
  }

  useEffect(() => {
    if (preview === null) return;
    return () => {
      URL.revokeObjectURL(preview);
    };
  }, [preview]);

  const analyse = useMutation({
    mutationFn: (screenshot: File) => importsApi.analyze(screenshot),
    onSuccess: (result) => {
      setDraft(result);
      setFields({
        kind: result.kind,
        date: result.date ?? '',
        type: result.workout_type ?? (result.kind === 'run' ? 'Course' : ''),
        distance_km: numberText(result.distance_km),
        duration_min: numberText(result.duration_min),
        avg_hr: numberText(result.avg_hr),
        elevation_m: numberText(result.elevation_m),
        calories: numberText(result.calories),
      });
      // Ce que la capture portait vraiment — l'inverse exact de `missing`.
      setProposed(Object.keys(FIELD_NAMES).filter((field) => !result.missing.includes(field)));
      setError(null);
    },
    onError: (caught: unknown) => {
      // Y compris la capture illisible (`IMP-06`) : le message du serveur dit quoi faire.
      notify(caught instanceof ApiError ? caught.message : 'Analyse impossible.', 'recover');
    },
  });

  const confirm = useMutation({
    mutationFn: () =>
      importsApi.confirm({
        kind: fields.kind,
        date: fields.date,
        duration_min: fields.duration_min,
        type: fields.type || (fields.kind === 'run' ? 'Course' : 'séance'),
        distance_km: fields.distance_km || null,
        avg_hr: fields.avg_hr || null,
        elevation_m: fields.elevation_m || null,
        calories: fields.calories || null,
      }),
    onSuccess: (result) => {
      invalidate();
      notify(
        result.kind === 'run'
          ? `Course importée — ${km(result.distance_km ?? 0)} en ${duration(result.duration_min)}.`
          : `Séance importée — ${duration(result.duration_min)}.`,
        'effort',
      );
      choose(null);
      if (fileInput.current) fileInput.current.value = '';
    },
    onError: (caught: unknown) => {
      setError(caught instanceof ApiError ? caught : null);
    },
  });

  /** Corriger une valeur proposée la fait sienne : la marque disparaît. */
  const set = (name: keyof ImportFields) => (value: string) => {
    setFields((current) => ({ ...current, [name]: value }));
    setProposed((current) => current.filter((field) => field !== name));
  };

  const missing = draft?.missing.filter((field) => field in FIELD_NAMES) ?? [];

  return (
    <Card>
      <h3>Import d&apos;une capture</h3>
      <p className={styles.note}>
        Une capture d&apos;Apple Fitness ou de la montre suffit : elle est lue, jamais enregistrée
        telle quelle. Tout reste modifiable avant l&apos;import.
      </p>

      <div className={styles.form}>
        {error !== null && (
          <p className={styles.error} role="alert">
            {error.message}
          </p>
        )}

        <input
          ref={fileInput}
          id="apple-screenshot"
          type="file"
          accept="image/jpeg,image/png,image/webp"
          className="sr-only"
          onChange={(event) => {
            choose(event.target.files?.[0] ?? null);
          }}
        />
        {preview !== null ? (
          <img className={styles.shot} src={preview} alt="Aperçu de la capture" />
        ) : (
          <label htmlFor="apple-screenshot" className={styles.drop}>
            choisir une capture d&apos;écran
          </label>
        )}

        {file !== null && draft === null && (
          <Button
            variant="ghost"
            busy={analyse.isPending}
            onClick={() => {
              analyse.mutate(file);
            }}
          >
            Lire la capture
          </Button>
        )}

        {draft !== null && (
          <>
            <AiBlock
              tag="Lecture de la capture"
              actions={
                <Button variant="quiet" onClick={reset}>
                  Pas d&apos;accord
                </Button>
              }
            >
              <p>
                Les champs en pointillé viennent de la capture.{' '}
                {missing.length > 0 ? (
                  <>
                    <strong>{missing.map((field) => FIELD_NAMES[field]).join(', ')}</strong>{' '}
                    {missing.length > 1 ? "n'y étaient pas" : "n'y était pas"} : le champ reste vide
                    plutôt que deviné.
                  </>
                ) : (
                  <>Tout y était. Corrige ce qui te semble faux.</>
                )}
              </p>
            </AiBlock>

            {draft.duplicate !== null && (
              <p className={styles.duplicate} role="status">
                <Badge tone="load">doublon probable</Badge> {draft.duplicate.label} du{' '}
                {shortDate(draft.duplicate.date)}, {duration(draft.duplicate.duration_min)} — déjà
                au journal. À toi de voir : deux sorties le même jour, cela existe.
              </p>
            )}

            <Segmented
              label="Nature de l'activité"
              value={fields.kind}
              onChange={(kind) => {
                setFields((current) => ({ ...current, kind }));
              }}
              options={[
                { value: 'run', label: 'Course' },
                { value: 'workout', label: 'Séance' },
              ]}
            />

            <div className={styles.pair}>
              <Field
                label="Date"
                type="date"
                value={fields.date}
                max={isoDay(new Date())}
                hint={fields.date === '' ? 'non lue sur la capture' : undefined}
                error={error?.messageFor('date')}
                onChange={(event) => {
                  set('date')(event.target.value);
                }}
              />
              <Field
                label={fields.kind === 'run' ? 'Type de course' : 'Type de séance'}
                placeholder={fields.kind === 'run' ? 'Course' : 'vélo'}
                value={fields.type}
                onChange={(event) => {
                  set('type')(event.target.value);
                }}
              />
            </div>

            <div className={styles.logGrid}>
              {fields.kind === 'run' && (
                <Stepper
                  label="Distance (km)"
                  value={fields.distance_km}
                  onChange={set('distance_km')}
                  step={0.5}
                  min={0}
                  proposed={proposed.includes('distance_km')}
                  error={error?.messageFor('distance_km')}
                />
              )}
              <Stepper
                label="Durée (min)"
                value={fields.duration_min}
                onChange={set('duration_min')}
                step={1}
                min={0}
                proposed={proposed.includes('duration_min')}
                error={error?.messageFor('duration_min')}
              />
              <Stepper
                label="FC moyenne"
                inputMode="numeric"
                value={fields.avg_hr}
                onChange={set('avg_hr')}
                step={5}
                min={0}
                proposed={proposed.includes('avg_hr')}
                error={error?.messageFor('avg_hr')}
              />
            </div>

            <div className={styles.logGrid}>
              <Stepper
                label="Dénivelé (m)"
                inputMode="numeric"
                value={fields.elevation_m}
                onChange={set('elevation_m')}
                step={10}
                min={0}
                proposed={proposed.includes('elevation_m')}
                error={error?.messageFor('elevation_m')}
              />
              <Stepper
                label="Calories"
                inputMode="numeric"
                value={fields.calories}
                onChange={set('calories')}
                step={25}
                min={0}
                proposed={proposed.includes('calories')}
                error={error?.messageFor('calories')}
              />
            </div>

            <Button
              variant="primary"
              className={styles.commit}
              busy={confirm.isPending}
              disabled={fields.date === '' || fields.duration_min === ''}
              onClick={() => {
                confirm.mutate();
              }}
            >
              Importer cette activité
            </Button>
            {(fields.date === '' || fields.duration_min === '') && (
              <p className={styles.empty}>
                La date et la durée manquent encore — ce sont les deux seules obligatoires.
              </p>
            )}
          </>
        )}
      </div>
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
        À déclarer une fois : l'exercice devient ensuite proposé dans le journal. Le retirer
        conserve tout l'historique — les performances passées restent lisibles sans lui.
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
  const ai = useAiStatus();
  const [picked, setPicked] = useState<Session | null>(null);

  // Choisir une séance depuis l'historique doit **se voir**. Le tableau est sous le
  // journal : sans ce défilement, cliquer « ouvrir » après avoir descendu la page ne
  // montrait rien du tout.
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
    mutationFn: (item: ActivityItem) => activityApi.duplicateWorkout(item.id, isoDay(new Date())),
    onSuccess: (workout) => {
      invalidate();
      setPicked(toSession(workout));
      notify('Séance dupliquée avec ses exercices.', 'effort');
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Duplication impossible.', 'recover');
    },
  });

  /**
   * Une activité de l'historique.
   *
   * Ce n'était pas une liste mais un tableau de six colonnes — illisible à 390 px, et une
   * ligne de tableau ne se tire pas au doigt. Les colonnes reviennent en grille dès qu'il
   * y a la place : c'est la même structure qui s'aligne, pas un second rendu.
   */
  function HistoryRow({ row }: { row: ActivityItem }) {
    return (
      <SwipeRow
        actionLabel={`Supprimer l'activité du ${shortDate(row.date)}`}
        busy={remove.isPending}
        onAction={() => {
          remove.mutate(row);
        }}
      >
        <div className={styles.histRow}>
          <span className={styles.histDate}>{shortDate(row.date)}</span>
          <span className={styles.histLabel}>
            {row.label}
            {/* Le serveur nomme déjà une course « Course » : répéter le mot faisait
                lire « Course · course ». Le suffixe ne sert que si le libellé se tait. */}
            {row.kind === 'run' && row.label.toLowerCase() !== 'course' && (
              <span className={styles.entryDetail}> · course</span>
            )}
          </span>

          {/* Le tiret est une **colonne vide**, pas une information. Il tient sa place
              tant qu'il y a des colonnes à aligner ; sur une fiche à 390 px, il ne
              laisserait qu'un trait orphelin sous la date. */}
          {row.distance_km !== null ? (
            <span className={styles.histNum}>{km(row.distance_km)}</span>
          ) : (
            <span className={cx(styles.histNum, styles.histNone)}>—</span>
          )}
          <span className={styles.histNum}>{duration(row.duration_min)}</span>
          {row.pace_min_km !== null ? (
            <span className={styles.histNum}>{pace(row.pace_min_km)}</span>
          ) : (
            <span className={cx(styles.histNum, styles.histNone)}>—</span>
          )}

          {row.kind === 'workout' && (
            <div className={styles.histActions}>
              <Chip
                aria-label={`Ouvrir la séance du ${shortDate(row.date)}`}
                onClick={() => {
                  // Choisir, pas charger. Le journal relit la séance lui-même et affiche
                  // en place ce que le serveur refuse ; ce bouton n'a plus de promesse à
                  // tenir, donc plus de refus à avaler.
                  setPicked({ id: row.id, date: row.date, label: row.label });
                }}
              >
                ouvrir
              </Chip>
              <Chip
                aria-label={`Dupliquer la séance du ${shortDate(row.date)}`}
                onClick={() => {
                  duplicate.mutate(row);
                }}
              >
                dupliquer
              </Chip>
            </div>
          )}
        </div>
      </SwipeRow>
    );
  }

  const week = data?.week;
  const today = isoDay(new Date());

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
    <div className="wrap">
      <PageHead eyebrow="Domaine Activité" title={<>Courses &amp; séances</>} />

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

      <Rule>Journal</Rule>
      <div ref={logRef}>
        <WorkoutJournal sessions={sessions} currentId={currentId} onPick={setPicked} />
      </div>

      <Rule>Saisie</Rule>
      <div className={styles.split}>
        <Card flush>
          <h3 className={styles.flushTitle}>
            Historique {data !== undefined && <span className={styles.empty}>· {data.total}</span>}
          </h3>
          {isPending ? (
            <p className={cx(styles.empty, styles.flushPad)}>chargement…</p>
          ) : data && data.history.length > 0 ? (
            <ul className={styles.history} aria-label="Historique des activités">
              {data.history.map((row) => (
                <li key={`${row.kind}-${row.id}-${row.token}`}>
                  <HistoryRow row={row} />
                </li>
              ))}
            </ul>
          ) : (
            <div className={styles.flushPad}>
              <Empty title="Aucune activité">
                Une sortie, une séance — la semaine commence à compter.
              </Empty>
            </div>
          )}
        </Card>

        {/* Ordre du geste réel : créer la séance que le journal ci-dessus attend, puis
            la course, puis — rarement, une fois pour toutes — le catalogue. */}
        <div className="stack">
          <Card>
            <h3>Nouvelle séance</h3>
            <WorkoutForm
              onCreated={(workout) => {
                setPicked(toSession(workout));
              }}
            />
          </Card>

          <Card>
            <h3>Nouvelle course</h3>
            <RunForm />
          </Card>

          {/* Même intention que le formulaire ci-dessus, par une autre porte. Sans clé, la
              carte n'apparaît pas : un import qui ne peut pas lire n'a rien à proposer, et
              les deux formulaires manuels suffisent à tout (`IA-07`). L'état de
              l'assistance se lit dans Réglages. */}
          {ai.enabled && <AppleImport />}

          <ExerciseCatalogue />
        </div>
      </div>
    </div>
  );
}
