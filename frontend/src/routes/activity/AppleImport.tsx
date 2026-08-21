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

import { useMutation } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';

import { AiBlock, Badge, Button, Card, Field, Segmented, Stepper } from '@/components/ui';
import { importsApi, type AppleDraft } from '@/features/imports/api';
import { ApiError } from '@/lib/api';
import { duration, km, shortDate } from '@/lib/format';
import { useToast } from '@/lib/toast';

import styles from '../Activity.module.css';
import { useInvalidateActivity } from './shared';

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

/** Les paliers pleins — le reliquat de fin n'en est pas un, et ne se compte pas avec eux. */
function fullSplits(draft: AppleDraft): number {
  return draft.splits.filter((split) => !split.partial).length;
}

export function AppleImport({ today }: { today: string | undefined }) {
  const invalidate = useInvalidateActivity();
  const { notify } = useToast();
  const fileInput = useRef<HTMLInputElement>(null);

  const [previews, setPreviews] = useState<string[]>([]);
  const [files, setFiles] = useState<File[]>([]);
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

  function choose(chosen: File[]) {
    setPreviews((current) => {
      // Les anciennes URL sont révoquées **avant** d'en créer d'autres : sans cela,
      // recommencer trois fois laisse trois images vivantes dans la mémoire de l'onglet.
      for (const url of current) URL.revokeObjectURL(url);
      return chosen.map((shot) => URL.createObjectURL(shot));
    });
    setFiles(chosen);
    // Un brouillon appartient aux captures qui l'ont produit.
    reset();
  }

  useEffect(() => {
    if (previews.length === 0) return;
    return () => {
      for (const url of previews) URL.revokeObjectURL(url);
    };
  }, [previews]);

  const analyse = useMutation({
    mutationFn: (screenshots: File[]) => importsApi.analyze(screenshots),
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
        // Ce que l'analyse a lu et qu'aucun champ ne montre : il traverse tel quel.
        // Le retoucher au pouce donnerait à l'écran les moyens de fausser ce que le
        // serveur vient de vérifier.
        total_calories: draft?.total_calories ?? null,
        start_time: draft?.start_time ?? null,
        end_time: draft?.end_time ?? null,
        split_length_km: draft?.split_length_km ?? null,
        splits: (draft?.splits ?? []).map((split) => ({
          index: split.index,
          duration_s: split.duration_s,
          pace_min_km: split.pace_min_km,
          cadence_spm: split.cadence_spm,
          avg_hr: split.avg_hr,
          elevation_m: split.elevation_m,
        })),
      }),
    onSuccess: (result) => {
      invalidate();
      notify(
        result.kind === 'run'
          ? `Course importée — ${km(result.distance_km ?? 0)} en ${duration(result.duration_min)}.`
          : `Séance importée — ${duration(result.duration_min)}.`,
        'effort',
      );
      choose([]);
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
          multiple
          className="sr-only"
          onChange={(event) => {
            choose(Array.from(event.target.files ?? []));
          }}
        />
        {previews.length > 0 ? (
          <div className={styles.shots}>
            {previews.map((url, index) => (
              <img
                className={styles.shot}
                src={url}
                key={url}
                alt={`Aperçu de la capture ${String(index + 1)}`}
              />
            ))}
          </div>
        ) : (
          <label htmlFor="apple-screenshot" className={styles.drop}>
            choisir une ou deux captures
          </label>
        )}

        {files.length > 0 && draft === null && (
          <Button
            variant="ghost"
            busy={analyse.isPending}
            onClick={() => {
              analyse.mutate(files);
            }}
          >
            {files.length > 1 ? `Lire les ${String(files.length)} captures` : 'Lire la capture'}
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

            {/* Les paliers ne se corrigent pas au champ près — on les valide en bloc ou
                on les laisse. L'écran dit donc ce qu'ils sont, et surtout ce que la
                relecture serveur en pense : une somme qui ne tombe pas les marque
                douteux, elle ne les refuse pas. */}
            {draft.splits.length > 0 && (
              <p className={styles.duplicate} role="status">
                {draft.splits_trusted ? (
                  <>
                    <Badge tone="effort">{fullSplits(draft)} paliers</Badge> relevés
                    {draft.splits.length > fullSplits(draft) && ' et un reliquat de fin'}. La somme
                    de leurs temps redonne la durée de la séance — ils seront enregistrés avec la
                    course.
                  </>
                ) : (
                  <>
                    <Badge tone="load">paliers douteux</Badge> {draft.splits_doubts.join(' ; ')}.
                    Ils seront enregistrés tels quels : compare à ta capture avant d&apos;importer.
                  </>
                )}
              </p>
            )}

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
                max={today}
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
