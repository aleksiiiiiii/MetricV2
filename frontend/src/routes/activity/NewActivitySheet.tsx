/**
 * Enregistrer une activité — un assistant, une étape par écran (`C06`).
 *
 * La feuille demandait tout d'un coup : nature, date, durée, type, effort, note, dans un
 * seul formulaire qu'il fallait parcourir en entier avant de savoir ce qui était
 * obligatoire. Elle demande maintenant **une chose à la fois**, et ce qu'elle demande
 * dépend de la première réponse.
 *
 * ```
 * étape 0   Course ou Séance ?
 *
 * Séance    1. date, durée, effort perçu          → Suivant
 *           2. les exercices, par la recherche    → Enregistrer
 *
 * Course    1. la capture, ou rien                → Suivant
 *           2. temps, allure, distance, cadence   → Enregistrer
 * ```
 *
 * ## Trois décisions
 *
 * **Rien n'est écrit avant le dernier appui.** La séance et ses exercices partent en un
 * seul appel — c'est ce que le backend accepte depuis ce lot. Abandonner à l'étape 2 ne
 * laisse donc aucune séance vide dans l'historique, ce qui était le prix de l'autre
 * découpage.
 *
 * **La charge d'un exercice se saisit en place, pas dans une seconde popup.** Le ticket
 * décrit « une popup demande poids, répétitions, séries » ; deux surfaces modales
 * empilées sur un téléphone de 360 px sont une impasse — on ne sait plus laquelle se
 * ferme, et la seconde recouvre la première. La ligne choisie **se déplie** à sa place et
 * porte les trois pas-à-pas. Le geste est le même, sans la pile.
 *
 * **Corriger une activité n'est pas un assistant.** Reprendre une séance déjà écrite
 * garde le formulaire d'un seul tenant : on vient changer un champ, pas dérouler un
 * parcours. C'est `ActivitySheet` qui s'en charge, inchangée.
 */

import { useMutation, useQuery } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';

import {
  Badge,
  Button,
  Chip,
  ChipStrip,
  Field,
  LogButton,
  Sheet,
  SheetRow,
  Stepper,
} from '@/components/ui';
import {
  activityApi,
  type Exercise,
  type ExerciseEntryPayload,
  type Workout,
} from '@/features/activity/api';
import { useAiStatus } from '@/features/ai/useAiStatus';
import { importsApi, type AppleDraft } from '@/features/imports/api';
import { ApiError } from '@/lib/api';
import { cx } from '@/lib/cx';
import { num, plural } from '@/lib/format';
import { fileSize, reduceImage } from '@/lib/image';
import { keys } from '@/lib/query';
import { useToast } from '@/lib/toast';

import styles from '../Activity.module.css';
import { NotesStep } from './NotesStep';
import { fold, useInvalidateActivity } from './shared';

/** Ce qu'un exercice ajouté à la séance porte, avant l'envoi. */
export interface DraftEntry extends ExerciseEntryPayload {
  /** Pour l'afficher sans relire le catalogue. */
  name: string;
  muscle_group: string;
}

type Kind = 'workout' | 'run';

/** Exercices proposés d'emblée, avant toute recherche — les plus récents. */
const SUGGESTED = 6;
const MATCHES = 8;

export function NewActivitySheet({
  open,
  today,
  onClose,
  onSaved,
}: {
  open: boolean;
  today: string;
  onClose: () => void;
  /** Rend la séance quand il y en a une : le journal s'ouvre dessus. */
  onSaved: (workout: Workout | null) => void;
}) {
  const [kind, setKind] = useState<Kind | null>(null);
  const [step, setStep] = useState(1);

  function reset(): void {
    setKind(null);
    setStep(1);
  }

  function close(): void {
    reset();
    onClose();
  }

  return (
    <Sheet
      open={open}
      onClose={close}
      title={kind === null ? 'Enregistrer une activité' : kind === 'run' ? 'Course' : 'Séance'}
      lede={
        kind === null
          ? 'De quoi s’agit-il ? Rien n’est enregistré avant ta validation.'
          : `Étape ${String(step)} sur 2`
      }
    >
      {kind === null ? (
        <div className={styles.modes}>
          <SheetRow
            label="Séance"
            hint="musculation, yoga, vélo…"
            aria-label="Séance"
            onClick={() => {
              setKind('workout');
            }}
          />
          <SheetRow
            label="Course"
            hint="temps, allure, distance"
            aria-label="Course"
            onClick={() => {
              setKind('run');
            }}
          />
        </div>
      ) : kind === 'workout' ? (
        <WorkoutWizard
          today={today}
          step={step}
          onStep={setStep}
          onBack={reset}
          onSaved={onSaved}
          onDone={close}
        />
      ) : (
        <RunWizard
          today={today}
          step={step}
          onStep={setStep}
          onBack={reset}
          onSaved={() => {
            onSaved(null);
          }}
          onDone={close}
        />
      )}
    </Sheet>
  );
}

// ── Parcours Séance ───────────────────────────────────

function WorkoutWizard({
  today,
  step,
  onStep,
  onBack,
  onSaved,
  onDone,
}: {
  today: string;
  step: number;
  onStep: (step: number) => void;
  onBack: () => void;
  onSaved: (workout: Workout) => void;
  onDone: () => void;
}) {
  const invalidate = useInvalidateActivity();
  const { notify } = useToast();
  const { data: types } = useQuery({ queryKey: keys.activity.types(), queryFn: activityApi.types });

  const [fields, setFields] = useState({
    date: today,
    type: 'musculation',
    duration_min: '',
    rpe: '',
    note: '',
  });
  const [entries, setEntries] = useState<DraftEntry[]>([]);
  const [error, setError] = useState<ApiError | null>(null);

  const save = useMutation({
    mutationFn: () =>
      activityApi.createWorkout({
        date: fields.date,
        type: fields.type,
        duration_min: fields.duration_min,
        rpe: fields.rpe ? Number(fields.rpe) : null,
        note: fields.note || null,
        exercises: entries.map((entry) => ({
          exercise_id: entry.exercise_id,
          weight_kg: entry.weight_kg,
          sets: entry.sets,
          reps: entry.reps,
        })),
      }),
    onSuccess: (workout) => {
      invalidate();
      notify(
        entries.length === 0
          ? 'Séance enregistrée. Ajoute tes exercices au journal.'
          : `Séance enregistrée avec ${String(entries.length)} ${plural(entries.length, 'exercice')}.`,
        'effort',
      );
      onSaved(workout);
      onDone();
    },
    onError: (caught: unknown) => {
      setError(caught instanceof ApiError ? caught : null);
    },
  });

  const set = (name: keyof typeof fields) => (event: { target: { value: string } }) => {
    setFields((current) => ({ ...current, [name]: event.target.value }));
  };

  if (step === 1) {
    return (
      <div className={styles.form}>
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
            max={today}
            error={error?.messageFor('date')}
            onChange={set('date')}
          />
          <Field
            label="Durée de séance"
            placeholder="1h15"
            hint="approximative : elle se corrige à la fin"
            value={fields.duration_min}
            error={error?.messageFor('duration_min')}
            onChange={set('duration_min')}
          />
        </div>

        {/* Le champ **puis** ses suggestions : une bande de pastilles posée avant un
            champ nommé « Type » se lisait comme un contrôle sans rapport avec lui. Le
            type reste libre (`ACT-03`) — les sept valeurs abrègent, elles ne contraignent
            pas. */}
        <Field
          label="Type de séance"
          placeholder="escalade…"
          value={fields.type}
          error={error?.messageFor('type')}
          onChange={set('type')}
        />
        <ChipStrip label="Types proposés">
          {(types ?? []).map((type) => (
            <Chip
              key={type}
              selected={fields.type === type}
              onClick={() => {
                setFields((current) => ({ ...current, type }));
              }}
            >
              {type}
            </Chip>
          ))}
        </ChipStrip>

        <Field
          label="Effort perçu (1–10)"
          inputMode="numeric"
          placeholder="8"
          value={fields.rpe}
          error={error?.messageFor('rpe')}
          onChange={set('rpe')}
        />

        <div className={styles.sheetCommit}>
          <Button
            variant="primary"
            className={styles.commit}
            disabled={fields.duration_min === '' || fields.type.trim() === ''}
            onClick={() => {
              onStep(2);
            }}
          >
            Suivant
          </Button>
          <Button variant="quiet" onClick={onBack}>
            Retour
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.form}>
      {error !== null && (
        <p className={styles.error} role="alert">
          {error.message}
        </p>
      )}

      <ExercisePicker
        entries={entries}
        onAdd={(entry) => {
          setEntries((current) => [...current, entry]);
        }}
        onRemove={(position) => {
          setEntries((current) => current.filter((_item, index) => index !== position));
        }}
      />

      <div className={styles.sheetCommit}>
        <Button
          variant="primary"
          className={styles.commit}
          busy={save.isPending}
          onClick={() => {
            save.mutate();
          }}
        >
          {entries.length === 0
            ? 'Enregistrer sans exercice'
            : `Enregistrer la séance (${String(entries.length)})`}
        </Button>
        <Button
          variant="quiet"
          disabled={save.isPending}
          onClick={() => {
            onStep(1);
          }}
        >
          Retour
        </Button>
      </div>
    </div>
  );
}

// ── L'étape 2 : chercher, puis chiffrer ───────────────

/**
 * La recherche dans le catalogue, et la saisie qui la suit.
 *
 * **Pas de seconde popup.** Appuyer sur un exercice le déplie à sa place, avec ses trois
 * pas-à-pas et son bouton. Deux surfaces modales empilées à 360 px sont une impasse : on
 * ne sait plus laquelle se ferme, et la seconde recouvre la première.
 */
function ExercisePicker({
  entries,
  onAdd,
  onRemove,
}: {
  entries: DraftEntry[];
  onAdd: (entry: DraftEntry) => void;
  onRemove: (position: number) => void;
}) {
  const ai = useAiStatus();
  const { data: catalogue } = useQuery({
    queryKey: keys.activity.exercises(),
    queryFn: activityApi.exercises,
  });

  const [query, setQuery] = useState('');
  const [picked, setPicked] = useState<Exercise | null>(null);
  const [notes, setNotes] = useState(false);
  const [form, setForm] = useState({ weight_kg: '', sets: '3', reps: '8' });

  const formRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (picked === null) return;
    formRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' });
  }, [picked]);

  const all = catalogue ?? [];
  const asked = fold(query.trim());
  const matched =
    asked === ''
      ? [...all].sort((a, b) => (b.last_date ?? '').localeCompare(a.last_date ?? ''))
      : all.filter(
          (item) => fold(item.name).includes(asked) || fold(item.muscle_group).includes(asked),
        );
  const shown = matched.slice(0, asked === '' ? SUGGESTED : MATCHES);
  const hidden = matched.length - shown.length;

  function add(): void {
    if (picked === null) return;
    onAdd({
      exercise_id: picked.exercise_id,
      name: picked.name,
      muscle_group: picked.muscle_group,
      weight_kg: form.weight_kg,
      sets: Number(form.sets.replace(',', '.')) || 1,
      reps: Number(form.reps.replace(',', '.')) || 1,
    });
    setPicked(null);
    setForm({ weight_kg: '', sets: '3', reps: '8' });
    setQuery('');
  }

  if (notes) {
    return (
      <NotesStep
        catalogue={all}
        onCancel={() => {
          setNotes(false);
        }}
        onAccepted={(lines) => {
          for (const line of lines) onAdd(line);
          setNotes(false);
        }}
      />
    );
  }

  return (
    <>
      {entries.length > 0 && (
        <div className={styles.entries}>
          <p className={styles.pickLabel}>
            {entries.length} {plural(entries.length, 'exercice')} {plural(entries.length, 'ajouté')}
          </p>
          {entries.map((entry, position) => (
            <div className={styles.draftRow} key={`${entry.exercise_id}-${String(position)}`}>
              <span>
                {entry.name}
                <span className={styles.entryDetail}>
                  {' · '}
                  {entry.weight_kg === '' || entry.weight_kg === '0'
                    ? 'poids du corps'
                    : `${entry.weight_kg} kg`}
                  {' · '}
                  {entry.sets}×{entry.reps}
                </span>
              </span>
              <Chip
                aria-label={`Retirer ${entry.name} de la séance`}
                onClick={() => {
                  onRemove(position);
                }}
              >
                Retirer
              </Chip>
            </div>
          ))}
        </div>
      )}

      {/* Les deux entrées de C07, au niveau où le ticket les place : dans l'étape 2.

          Un libellé **court**. « Coller mes notes ou photographier » faisait une pastille
          aussi large que la feuille, collée à ses deux bords — elle se lisait comme un
          champ, pas comme une cible. C'est le même défaut que « Cet exercice n'est pas
          dans la liste ? » avait produit, et la même correction : nommer l'action. */}
      {ai.enabled && (
        <div className={styles.missing}>
          <Chip
            aria-label="Saisir la séance depuis des notes ou une photo"
            onClick={() => {
              setNotes(true);
            }}
          >
            Depuis mes notes
          </Chip>
        </div>
      )}

      <Field
        label="Chercher un exercice"
        type="search"
        placeholder="nom ou groupe musculaire…"
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
        }}
      />

      <div className={styles.pickList} role="group" aria-label="Exercices proposés">
        {shown.map((item) => (
          <LogButton
            key={item.exercise_id}
            label={item.name}
            hint={
              item.last_weight_kg == null
                ? item.muscle_group
                : item.last_weight_kg === 0
                  ? 'poids du corps'
                  : `${num(item.last_weight_kg, 1)} kg`
            }
            aria-pressed={picked?.exercise_id === item.exercise_id}
            className={cx(picked?.exercise_id === item.exercise_id && styles.pickOn)}
            onClick={() => {
              setPicked(item);
              // Les séries et réps de la dernière fois : des valeurs **mesurées**, que le
              // catalogue rend (`ACT-08`). La charge reste vide, c'est elle qui progresse.
              setForm({
                weight_kg: '',
                sets: item.last_sets == null ? '3' : String(item.last_sets),
                reps: item.last_reps == null ? '8' : String(item.last_reps),
              });
            }}
          />
        ))}
      </div>

      {shown.length === 0 ? (
        <span className={styles.empty}>
          {all.length === 0
            ? 'catalogue vide — déclare un exercice depuis /activite/catalogue'
            : 'aucun exercice ne correspond'}
        </span>
      ) : (
        hidden > 0 && (
          <span className={styles.empty}>
            {hidden} {plural(hidden, 'autre')} au catalogue
            {asked === '' ? ' — cherche par nom ou groupe' : ' — précise ta recherche'}
          </span>
        )
      )}

      {/* La saisie se déplie **à la place** de la ligne choisie, sans empiler une seconde
          surface modale par-dessus la feuille. */}
      {picked !== null && (
        <div className={styles.draftForm} ref={formRef}>
          <p className={styles.pickLabel}>
            {picked.name} <Badge tone="signal">{picked.muscle_group}</Badge>
          </p>
          <div className={styles.logGrid}>
            <Stepper
              label="Charge (kg)"
              value={form.weight_kg}
              onChange={(value) => {
                setForm((current) => ({ ...current, weight_kg: value }));
              }}
              step={2.5}
              min={0}
              placeholder="0 = poids du corps"
            />
            <Stepper
              label="Séries"
              inputMode="numeric"
              value={form.sets}
              onChange={(value) => {
                setForm((current) => ({ ...current, sets: value }));
              }}
              min={1}
              max={20}
            />
            <Stepper
              label="Réps"
              inputMode="numeric"
              value={form.reps}
              onChange={(value) => {
                setForm((current) => ({ ...current, reps: value }));
              }}
              min={1}
              max={50}
            />
          </div>
          <div className={styles.sheetCommit}>
            <Button variant="primary" className={styles.commit} onClick={add}>
              Ajouter à la séance
            </Button>
            <Button
              variant="quiet"
              onClick={() => {
                setPicked(null);
              }}
            >
              Annuler
            </Button>
          </div>
        </div>
      )}
    </>
  );
}

// ── Parcours Course ───────────────────────────────────

/** Les champs d'une course, tous en texte jusqu'au serveur (`ACT-01`). */
interface RunFields {
  date: string;
  duration_min: string;
  distance_km: string;
  pace_min_km: string;
  cadence_spm: string;
  avg_hr: string;
  note: string;
}

function RunWizard({
  today,
  step,
  onStep,
  onBack,
  onSaved,
  onDone,
}: {
  today: string;
  step: number;
  onStep: (step: number) => void;
  onBack: () => void;
  onSaved: () => void;
  onDone: () => void;
}) {
  const invalidate = useInvalidateActivity();
  const { notify } = useToast();
  const ai = useAiStatus();

  const [fields, setFields] = useState<RunFields>({
    date: today,
    duration_min: '',
    distance_km: '',
    pace_min_km: '',
    cadence_spm: '',
    avg_hr: '',
    note: '',
  });
  /** Ce qui vient de la capture et n'a pas encore été retouché (`IMP-02`). */
  const [proposed, setProposed] = useState<string[]>([]);
  /**
   * Le dernier des deux champs liés qu'on a touché.
   *
   * Distance et allure sont deux lectures du même trajet, et le **serveur** calcule l'une
   * depuis l'autre. Quand les deux sont remplies, il faut lui dire laquelle défendre :
   * c'est celle qu'on vient de corriger. Sans ce choix, l'écran enverrait les deux et la
   * règle du serveur trancherait à l'aveugle.
   */
  const [edited, setEdited] = useState<'distance' | 'pace' | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  const save = useMutation({
    mutationFn: () =>
      activityApi.createRun({
        date: fields.date,
        duration_min: fields.duration_min,
        // On n'envoie que celui qu'on défend, quand les deux sont là.
        distance_km: edited === 'pace' ? null : fields.distance_km || null,
        pace_min_km: edited === 'distance' ? null : fields.pace_min_km || null,
        cadence_spm: fields.cadence_spm || null,
        avg_hr: fields.avg_hr || null,
        note: fields.note || null,
      }),
    onSuccess: () => {
      invalidate();
      notify('Course enregistrée.', 'effort');
      onSaved();
      onDone();
    },
    onError: (caught: unknown) => {
      setError(caught instanceof ApiError ? caught : null);
    },
  });

  const set = (name: keyof RunFields) => (value: string) => {
    setFields((current) => ({ ...current, [name]: value }));
    // Corriger une valeur proposée la fait sienne : la marque disparaît.
    setProposed((current) => current.filter((field) => field !== name));
    if (name === 'distance_km') setEdited('distance');
    if (name === 'pace_min_km') setEdited('pace');
  };

  if (step === 1) {
    return (
      <AppleStep
        today={today}
        enabled={ai.enabled}
        onSkip={() => {
          onStep(2);
        }}
        onBack={onBack}
        onRead={(draft) => {
          setFields((current) => ({
            ...current,
            date: draft.date ?? current.date,
            duration_min: draft.duration_min == null ? '' : String(draft.duration_min),
            distance_km: draft.distance_km == null ? '' : String(draft.distance_km),
            pace_min_km: draft.pace_min_km == null ? '' : String(draft.pace_min_km),
            cadence_spm: draft.cadence_spm == null ? '' : String(draft.cadence_spm),
            avg_hr: draft.avg_hr == null ? '' : String(draft.avg_hr),
          }));
          setProposed(
            (
              [
                'date',
                'duration_min',
                'distance_km',
                'pace_min_km',
                'cadence_spm',
                'avg_hr',
              ] as const
            )
              .filter((field) => !draft.missing.includes(field))
              .map(String),
          );
          setEdited(null);
          onStep(2);
        }}
      />
    );
  }

  return (
    <div className={styles.form}>
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
          max={today}
          error={error?.messageFor('date')}
          onChange={(event) => {
            set('date')(event.target.value);
          }}
        />
        <Field
          label="Temps"
          placeholder="44:12 ou 1h30"
          hint="mm:ss, h:mm:ss ou minutes"
          value={fields.duration_min}
          error={error?.messageFor('duration_min')}
          onChange={(event) => {
            set('duration_min')(event.target.value);
          }}
        />
      </div>

      {/* Distance **et** allure sont modifiables, et le serveur recalcule celle qu'on n'a
          pas touchée. C'est pour cela qu'elles sont côte à côte : leur lien se voit. */}
      <div className={styles.pair}>
        <Stepper
          label="Distance (km)"
          value={fields.distance_km}
          onChange={set('distance_km')}
          step={0.5}
          min={0}
          proposed={proposed.includes('distance_km')}
          error={error?.messageFor('distance_km')}
        />
        <Field
          label="Allure (min/km)"
          placeholder="5:16"
          hint={
            edited === 'pace'
              ? 'la distance sera recalculée'
              : edited === 'distance'
                ? 'l’allure sera recalculée'
                : 'l’une des deux suffit'
          }
          value={fields.pace_min_km}
          error={error?.messageFor('pace_min_km')}
          onChange={(event) => {
            set('pace_min_km')(event.target.value);
          }}
        />
      </div>

      <div className={styles.logGrid}>
        <Stepper
          label="Cadence (SPM)"
          inputMode="numeric"
          value={fields.cadence_spm}
          onChange={set('cadence_spm')}
          step={1}
          min={0}
          proposed={proposed.includes('cadence_spm')}
          error={error?.messageFor('cadence_spm')}
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

      <Field
        label="Ressenti"
        placeholder="jambes lourdes, vent de face…"
        value={fields.note}
        onChange={(event) => {
          setFields((current) => ({ ...current, note: event.target.value }));
        }}
      />

      <div className={styles.sheetCommit}>
        <Button
          variant="primary"
          className={styles.commit}
          busy={save.isPending}
          disabled={
            fields.duration_min === '' || (fields.distance_km === '' && fields.pace_min_km === '')
          }
          onClick={() => {
            save.mutate();
          }}
        >
          Enregistrer la course
        </Button>
        <Button
          variant="quiet"
          disabled={save.isPending}
          onClick={() => {
            onStep(1);
          }}
        >
          Retour
        </Button>
      </div>

      {fields.duration_min !== '' && fields.distance_km === '' && fields.pace_min_km === '' && (
        <p className={styles.empty}>
          Il manque encore la distance, ou l’allure. Le serveur calcule celle que tu ne donnes pas.
        </p>
      )}
    </div>
  );
}

// ── L'étape 1 d'une course : la capture ───────────────

function AppleStep({
  today,
  enabled,
  onRead,
  onSkip,
  onBack,
}: {
  today: string;
  enabled: boolean;
  onRead: (draft: AppleDraft) => void;
  onSkip: () => void;
  onBack: () => void;
}) {
  const { notify } = useToast();
  const fileInput = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [weight, setWeight] = useState<number | null>(null);

  useEffect(() => {
    if (preview === null) return;
    return () => {
      URL.revokeObjectURL(preview);
    };
  }, [preview]);

  const choose = useMutation({
    mutationFn: async (chosen: File | null) => (chosen === null ? null : reduceImage(chosen)),
    onSuccess: (result) => {
      setPreview((current) => {
        if (current) URL.revokeObjectURL(current);
        return result ? URL.createObjectURL(result.file) : null;
      });
      setFile(result?.file ?? null);
      setWeight(result?.file.size ?? null);
    },
    onError: () => {
      notify('Cette image n’a pas pu être lue. Essaie une autre capture.', 'recover');
    },
  });

  const read = useMutation({
    // Une seule capture ici : cette étape lit un résumé pour pré-remplir une saisie, et
    // n'a pas de tableau de paliers à recoller. L'import de `/activite` en accepte deux.
    mutationFn: (screenshot: File) => importsApi.analyze([screenshot]),
    onSuccess: onRead,
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Lecture impossible.', 'recover');
    },
  });

  return (
    <div className={styles.form}>
      <p className={styles.note}>
        {enabled
          ? 'Une capture d’Apple Fitness ou de la montre suffit : elle est lue, jamais enregistrée telle quelle. Tout reste modifiable ensuite.'
          : 'La lecture de capture demande une clé OpenRouter. La saisie à la main reste entière.'}
      </p>

      {enabled && (
        <>
          <input
            ref={fileInput}
            id="apple-screenshot"
            type="file"
            accept="image/jpeg,image/png,image/webp"
            className="sr-only"
            onChange={(event) => {
              choose.mutate(event.target.files?.[0] ?? null);
            }}
          />
          {preview !== null ? (
            <img className={styles.shot} src={preview} alt="Aperçu de la capture" />
          ) : (
            <label htmlFor="apple-screenshot" className={styles.drop}>
              {choose.isPending ? 'réduction…' : 'choisir une capture d’écran'}
            </label>
          )}
          {weight !== null && (
            <span className={styles.empty}>{fileSize(weight)} — réduite avant l’envoi</span>
          )}
        </>
      )}

      <div className={styles.sheetCommit}>
        {enabled && file !== null ? (
          <Button
            variant="primary"
            className={styles.commit}
            busy={read.isPending}
            onClick={() => {
              read.mutate(file);
            }}
          >
            Lire la capture
          </Button>
        ) : (
          <Button variant="primary" className={styles.commit} onClick={onSkip}>
            Saisir à la main
          </Button>
        )}
        <Button variant="quiet" onClick={onBack}>
          Retour
        </Button>
      </div>

      {enabled && file !== null && (
        <Button variant="quiet" onClick={onSkip}>
          Passer, et saisir à la main
        </Button>
      )}

      <p className={styles.empty}>Aujourd’hui : {today}</p>
    </div>
  );
}
