/**
 * Import d'une capture Apple Fitness (`IMP-01` → `IMP-06`).
 *
 * ## Quatre étapes, et elles se nomment
 *
 * Le parcours était le même mais **muet** : la carte se dépliait toute seule au fil des
 * appuis, sans jamais dire où l'on en était ni ce qui restait à faire. Elle l'annonce
 * maintenant — ouvrir, ajouter les captures, vérifier ce qui a été ajouté, valider ce que
 * le modèle a lu.
 *
 * **La troisième étape est celle qui manquait.** Les vignettes apparaissaient au même
 * instant que le bouton de lecture, si bien qu'on lançait le modèle sans avoir regardé ce
 * qu'on lui donnait — et une capture de travers ne se voyait qu'après l'appel. Elle a
 * maintenant son temps propre : on voit ce qui part, on peut en retirer une, et **c'est
 * le seul écran où l'on peut encore le faire**.
 *
 * L'étape courante se **déduit** de l'état plutôt que d'être stockée à côté de lui : un
 * compteur qu'on incrémente à la main finit toujours par désigner une étape que la donnée
 * ne porte plus.
 *
 * ## Ce que les étapes ne changent pas
 *
 * La frontière entre lire et écrire reste le contrat du lot (`IMP-01`) : rien ne passe de
 * la lecture à l'écriture sans un appui. Et le pré-remplissage n'est pas un formulaire en
 * lecture seule qu'on validerait en bloc — chaque valeur est un pas-à-pas, corrigeable au
 * pouce (`IMP-02`). Une valeur qu'on ne peut pas retoucher est une valeur qu'on adopte
 * faute de mieux.
 */

import { useMutation } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';

import { AiBlock, Badge, Button, Card, Field, Segmented, Stepper, Steps } from '@/components/ui';
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

/**
 * Les quatre temps du parcours. L'ordre **est** le parcours : l'écran en déduit où il en
 * est, il ne tient pas de compteur en parallèle.
 */
const STEPS = ['Ouvrir', 'Ajouter les captures', 'Vérifier', 'Valider'] as const;

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

  // La seule chose que le parcours ait besoin de retenir : le reste se déduit.
  const [open, setOpen] = useState(false);
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
    // Choisir une capture **engage** le parcours, même si l'on n'est pas passé par le
    // bouton d'ouverture — un glisser-déposer ou un champ natif rappelé par le système
    // y mènent aussi. Sans cela, retirer la dernière capture repliait toute la carte
    // au lieu de revenir à l'étape d'ajout, et l'on perdait l'intention d'importer.
    if (chosen.length > 0) setOpen(true);
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
      // Le parcours se referme sur lui-même : la course est écrite, et laisser la carte
      // dépliée sur une étape 2 vide donnerait l'impression qu'il reste quelque chose à
      // faire. Elle se rouvre d'un appui.
      setOpen(false);
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

  /** Retire une capture avant lecture — le seul écran où c'est encore possible. */
  function drop(index: number) {
    const kept = files.filter((_, position) => position !== index);
    choose(kept);
    // Le champ natif garde sa liste : sans ce vidage, rechoisir le **même** fichier
    // n'émettrait aucun `change` et l'écran resterait sur une capture qu'on vient
    // d'écarter.
    if (fileInput.current) fileInput.current.value = '';
  }

  // L'étape se lit dans la donnée, elle ne se compte pas à côté. Un brouillon existe :
  // on valide. Des fichiers sans brouillon : on vérifie. Ouvert sans fichier : on ajoute.
  const step = draft !== null ? 3 : files.length > 0 ? 2 : open ? 1 : 0;

  return (
    <Card>
      <h3>Import d&apos;une capture</h3>
      <p className={styles.note}>
        Une capture d&apos;Apple Fitness ou de la montre suffit : elle est lue, jamais enregistrée
        telle quelle. Tout reste modifiable avant l&apos;import.
      </p>

      {/* Le fil n'apparaît qu'une fois le parcours engagé : sur une carte repliée, il
          annoncerait quatre étapes à quelqu'un qui n'en a demandé aucune. */}
      {open && <Steps steps={STEPS} current={step} />}

      <div className={styles.form}>
        {error !== null && (
          <p className={styles.error} role="alert">
            {error.message}
          </p>
        )}

        {/* ── Étape 1 — ouvrir ─────────────────────── */}
        {!open && (
          <Button
            variant="ghost"
            onClick={() => {
              setOpen(true);
            }}
          >
            Importer une capture
          </Button>
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
        {/* ── Étape 2 — ajouter les captures ───────── */}
        {open && files.length === 0 && (
          <>
            <label htmlFor="apple-screenshot" className={styles.drop}>
              choisir une ou plusieurs captures
            </label>
            <p className={styles.note}>
              Le résumé de la séance, et la liste « Splits » si tu l&apos;as : les paliers ne se
              lisent que sur cette seconde capture.
            </p>
          </>
        )}

        {/* ── Étape 3 — vérifier ce qui a été ajouté ──
            Elle n'existait pas : les vignettes arrivaient en même temps que le bouton de
            lecture, et l'on envoyait au modèle des captures qu'on n'avait pas regardées.
            C'est aussi le dernier moment où l'on peut en retirer une. */}
        {previews.length > 0 && (
          <>
            <p className={styles.note} role="status">
              {previews.length > 1
                ? `${String(previews.length)} captures prêtes à être lues.`
                : 'Une capture prête à être lue.'}
              {draft === null && ' Vérifie qu’elles sont nettes et complètes.'}
            </p>
            <div className={styles.shots}>
              {previews.map((url, index) => (
                <figure className={styles.shotBox} key={url}>
                  <img
                    className={styles.shot}
                    src={url}
                    alt={`Aperçu de la capture ${String(index + 1)}`}
                  />
                  {draft === null && (
                    <button
                      type="button"
                      className={styles.shotDrop}
                      onClick={() => {
                        drop(index);
                      }}
                    >
                      {/* Une addition se défait sans confirmation : c'est la suppression
                          que l'utilisateur ferait, et rien n'est encore écrit. */}
                      Retirer<span className="sr-only"> la capture {index + 1}</span>
                    </button>
                  )}
                </figure>
              ))}
            </div>
          </>
        )}

        {files.length > 0 && draft === null && (
          <>
            <Button
              variant="ghost"
              busy={analyse.isPending}
              onClick={() => {
                analyse.mutate(files);
              }}
            >
              {files.length > 1 ? `Lire les ${String(files.length)} captures` : 'Lire la capture'}
            </Button>
            <label htmlFor="apple-screenshot" className={styles.drop}>
              ajouter d&apos;autres captures
            </label>
          </>
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
