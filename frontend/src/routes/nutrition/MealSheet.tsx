/**
 * Ajouter un repas — quatre modes de saisie, une seule feuille.
 *
 * Le formulaire était **déplié en permanence** au bas de l'écran : un sélecteur de type,
 * une zone de photo, une description et trois pas-à-pas, tout le temps, qu'on vienne
 * photographier son assiette ou taper trois nombres lus sur un emballage. Il demandait
 * donc de traverser ce dont on n'avait pas besoin pour atteindre ce qu'on voulait.
 *
 * Une feuille, et **le mode d'abord** : photo, photo et description, description seule,
 * ou les trois nombres à la main. Le mode ne change pas ce qui est enregistré — un repas
 * reste un repas — il change ce que la feuille demande et ce qu'elle propose d'estimer.
 *
 * ## Ce qui n'a pas bougé, et pourquoi
 *
 * **Une valeur proposée n'est pas une mesure.** L'estimation arrive dans un `AiBlock`, se
 * pose dans des pas-à-pas marqués `proposed`, et la marque disparaît dès qu'on retouche.
 * C'est la seule façon dont le projet le dit, et elle n'est pas redite ici autrement.
 *
 * **Rien n'est écrit avant le dernier appui.** L'estimation ne touche pas au stockage, la
 * photo n'est rangée qu'à l'enregistrement, et les quatre portes de sortie de `Sheet`
 * ferment sans rien laisser — à n'importe quelle étape, y compris pendant l'attente.
 *
 * ## La photo est réduite avant de partir
 *
 * `lib/image.ts` la ramène à 1600 px et la réencode en JPEG. Une photo d'iPhone brute fait
 * cinq à huit mégaoctets et se faisait refuser par le reverse-proxy avec un `413` nu.
 * L'écran annonce le poids réel de ce qui part : c'est la seule façon de savoir, du côté
 * de l'utilisateur, que la réduction a bien eu lieu.
 */

import { useMutation } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';

import { AiBlock, Button, Field, Sheet, SheetRow, Stepper } from '@/components/ui';
import { useAiStatus } from '@/features/ai/useAiStatus';
import { nutritionApi, type MealEstimate, type MealFormValues } from '@/features/nutrition/api';
import { ApiError } from '@/lib/api';
import { cx } from '@/lib/cx';
import { fileSize, reduceImage } from '@/lib/image';
import { useToast } from '@/lib/toast';

import styles from '../Nutrition.module.css';
import { estimateSentence } from './estimate';

/** Les trois macros qu'une estimation peut proposer, et que l'écran marque comme telles. */
type Macro = 'protein_g' | 'added_sugar_g' | 'calories';

/** Les quatre modes du ticket, dans l'ordre où ils sont proposés. */
type Mode = 'photo' | 'photo-texte' | 'texte' | 'manuel';

const MODES: { value: Mode; label: string; hint: string }[] = [
  { value: 'photo', label: 'Photo', hint: 'l’assiette suffit' },
  { value: 'photo-texte', label: 'Photo et description', hint: 'le plus précis' },
  { value: 'texte', label: 'Description', hint: 'sans photo' },
  { value: 'manuel', label: 'Valeurs à la main', hint: 'protéines, sucres, calories' },
];

/** Le mode demande-t-il une photo ? */
function wantsPhoto(mode: Mode): boolean {
  return mode === 'photo' || mode === 'photo-texte';
}

/** Le mode demande-t-il une description ? */
function wantsText(mode: Mode): boolean {
  return mode === 'photo-texte' || mode === 'texte';
}

/** Le mode passe-t-il par une estimation ? Le quatrième, non — c'est tout son sens. */
function wantsEstimate(mode: Mode): boolean {
  return mode !== 'manuel';
}

const EMPTY: MealFormValues = {
  meal_type: '',
  comment: '',
  protein_g: '',
  added_sugar_g: '',
  calories: '',
  photo: null,
  source: 'manual',
};

export function MealSheet({
  open,
  onClose,
  onSaved,
  suggested,
  types,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  suggested: string;
  types: string[];
}) {
  const { notify } = useToast();
  const ai = useAiStatus();
  const fileInput = useRef<HTMLInputElement>(null);

  const [mode, setMode] = useState<Mode | null>(null);
  const [values, setValues] = useState<MealFormValues>(EMPTY);
  const [preview, setPreview] = useState<string | null>(null);
  const [weight, setWeight] = useState<number | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  // Ce que le modèle a proposé, et lesquelles de ces valeurs sont encore les siennes.
  // Deux états et non un : une valeur retouchée cesse d'être une proposition, mais
  // l'estimation reste affichée — elle explique d'où vient ce qui est dans les champs.
  const [estimate, setEstimate] = useState<MealEstimate | null>(null);
  const [proposed, setProposed] = useState<Macro[]>([]);

  // Révocation au démontage : sans elle, fermer la feuille avec un aperçu ouvert fuirait
  // sa mémoire jusqu'au rechargement.
  useEffect(() => {
    if (preview === null) return;
    return () => {
      URL.revokeObjectURL(preview);
    };
  }, [preview]);

  /** Tout remettre à zéro — c'est ce que « annuler » veut dire, à n'importe quelle étape. */
  function reset(): void {
    setMode(null);
    setValues(EMPTY);
    setPreview((current) => {
      if (current) URL.revokeObjectURL(current);
      return null;
    });
    setWeight(null);
    setEstimate(null);
    setProposed([]);
    setError(null);
    if (fileInput.current) fileInput.current.value = '';
  }

  function close(): void {
    reset();
    onClose();
  }

  /**
   * « Pas d'accord » — et l'action fait vraiment ce qu'elle dit.
   *
   * Les valeurs **encore proposées** sont vidées, celles que l'utilisateur a retouchées
   * restent : elles sont à lui. La provenance retombe sur `manual`, sans quoi le fichier
   * dirait « ai » sur un repas dont l'estimation a été refusée.
   */
  function reject(): void {
    setValues((current) => {
      const cleared = { ...current, source: 'manual' as const };
      for (const macro of proposed) cleared[macro] = '';
      return cleared;
    });
    setProposed([]);
    setEstimate(null);
  }

  /** La photo est réduite **au moment du choix**, pas à l'envoi : le poids se lit avant. */
  const choose = useMutation({
    mutationFn: async (file: File | null) => {
      if (file === null) return null;
      return reduceImage(file);
    },
    onSuccess: (result) => {
      setPreview((current) => {
        if (current) URL.revokeObjectURL(current);
        return result ? URL.createObjectURL(result.file) : null;
      });
      setValues((current) => ({ ...current, photo: result?.file ?? null }));
      setWeight(result?.file.size ?? null);
      // Une estimation appartient à la photo qui l'a produite : changer de photo sans la
      // jeter laisserait des macros d'une autre assiette.
      reject();
    },
    onError: () => {
      notify('Cette image n’a pas pu être lue. Essaie une autre photo.', 'recover');
    },
  });

  const suggest = useMutation({
    mutationFn: () => nutritionApi.analyze(values.photo, values.comment),
    onSuccess: setEstimate,
    onError: (caught: unknown) => {
      // Un refus de l'IA se dit et s'oublie : la saisie manuelle reste entière (`IA-07`).
      // Le refus de taille, lui, porte maintenant un code et une phrase française —
      // c'était un `413` nu, donc un échec sans message.
      notify(caught instanceof ApiError ? caught.message : 'Estimation impossible.', 'recover');
    },
  });

  /** Applique la proposition aux champs, et retient lesquels en viennent (`NUT-04`). */
  function accept(result: MealEstimate): void {
    const filled: Macro[] = [];
    setValues((current) => {
      const next = { ...current, source: 'ai' as const };
      if (result.protein_g !== null) {
        next.protein_g = fieldText(result.protein_g);
        filled.push('protein_g');
      }
      if (result.added_sugar_g !== null) {
        next.added_sugar_g = fieldText(result.added_sugar_g);
        filled.push('added_sugar_g');
      }
      if (result.calories !== null) {
        next.calories = fieldText(result.calories);
        filled.push('calories');
      }
      // La description ne remplace jamais celle qui a été tapée : ce qu'on écrit soi-même
      // décrit mieux son repas que ce qu'un modèle voit sur une photo.
      if (result.comment !== null && current.comment.trim() === '') next.comment = result.comment;
      return next;
    });
    setProposed(filled);
  }

  const save = useMutation({
    mutationFn: () => nutritionApi.create({ ...values, meal_type: values.meal_type || suggested }),
    onSuccess: () => {
      notify('Repas enregistré.', 'effort');
      reset();
      onSaved();
    },
    onError: (caught: unknown) => {
      setError(caught instanceof ApiError ? caught : null);
    },
  });

  const setMacro = (name: Macro) => (value: string) => {
    setValues((current) => ({ ...current, [name]: value }));
    // Retoucher une proposition la fait sienne, et la marque disparaît.
    setProposed((current) => current.filter((macro) => macro !== name));
  };

  const sentence = estimate === null ? '' : estimateSentence(estimate);
  const nothingToLog = values.comment.trim() === '' && values.photo === null;
  const nothingToEstimate = values.photo === null && values.comment.trim() === '';
  const busy = choose.isPending || suggest.isPending || save.isPending;

  return (
    <Sheet
      open={open}
      onClose={close}
      title="Ajouter un repas"
      lede={
        mode === null
          ? 'Comment veux-tu le noter ? Rien n’est enregistré avant ta validation.'
          : undefined
      }
    >
      {mode === null ? (
        <div className={styles.modes}>
          {MODES.filter((item) => ai.enabled || item.value === 'manuel').map((item) => (
            /* `SheetRow` et non `LogButton` : c'est la ligne que la charte réserve aux
               feuilles — pleine largeur, `--tap-lg`, libellé à gauche et indice à droite.
               `LogButton` est le vocabulaire de la saisie rapide, où l'indice est une
               **mesure** rappelée ; ici c'est une phrase, et le rendre en chasse fixe la
               faisait passer pour un relevé. */
            <SheetRow
              key={item.value}
              label={item.label}
              hint={item.hint}
              // L'indice explique le choix, il ne le décrit pas : l'annoncer rallongerait
              // chaque entrée d'une phrase qu'on entend quatre fois de suite.
              aria-label={item.label}
              onClick={() => {
                setMode(item.value);
              }}
            />
          ))}
          {/* Sans clé, les trois premiers modes n'ont rien à proposer : ils ne sont pas
              affichés grisés, ils ne sont pas affichés (`IA-07`). L'écran dit pourquoi
              plutôt que de laisser trois portes fermées. */}
          {!ai.enabled && <p className={styles.note}>{ai.message}</p>}
        </div>
      ) : (
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

          <div className={styles.field}>
            <label htmlFor="meal-type">Type</label>
            <select
              id="meal-type"
              className={styles.select}
              value={values.meal_type || suggested}
              onChange={(event) => {
                setValues((current) => ({ ...current, meal_type: event.target.value }));
              }}
            >
              {types.map((type) => (
                <option value={type} key={type}>
                  {type}
                </option>
              ))}
            </select>
          </div>

          {wantsPhoto(mode) && (
            <div className={styles.field}>
              <label htmlFor="meal-photo">Photo</label>
              <input
                ref={fileInput}
                id="meal-photo"
                type="file"
                accept="image/jpeg,image/png,image/webp,image/heic"
                capture="environment"
                className="sr-only"
                onChange={(event) => {
                  choose.mutate(event.target.files?.[0] ?? null);
                }}
              />
              {preview !== null ? (
                <img className={styles.preview} src={preview} alt="Aperçu du repas" />
              ) : (
                <label htmlFor="meal-photo" className={styles.drop}>
                  {choose.isPending ? 'réduction…' : 'prendre ou choisir une photo'}
                </label>
              )}
              {/* Le poids réel de ce qui partira. Sans lui, rien à l'écran ne dit que la
                  réduction a eu lieu — et c'est précisément ce qui manquait le jour où
                  l'envoi se faisait refuser sans explication. */}
              {weight !== null && (
                <span className={styles.empty}>{fileSize(weight)} — réduite avant l’envoi</span>
              )}
            </div>
          )}

          {(wantsText(mode) || mode === 'manuel') && (
            <Field
              label="Description"
              placeholder="poulet, riz, brocolis"
              value={values.comment}
              error={error?.messageFor('comment')}
              onChange={(event) => {
                setValues((current) => ({ ...current, comment: event.target.value }));
              }}
            />
          )}

          {wantsEstimate(mode) &&
            (estimate === null ? (
              <Button
                variant="ghost"
                busy={suggest.isPending}
                disabled={nothingToEstimate || choose.isPending}
                onClick={() => {
                  suggest.mutate();
                }}
              >
                Estimer les macros
              </Button>
            ) : (
              <AiBlock
                tag={proposed.length > 0 ? 'Estimation appliquée' : 'Estimation'}
                actions={
                  proposed.length > 0 || estimate.empty || !estimate.readable ? (
                    <Button variant="quiet" onClick={reject}>
                      Pas d&apos;accord
                    </Button>
                  ) : (
                    <>
                      <Button
                        variant="primary"
                        onClick={() => {
                          accept(estimate);
                        }}
                      >
                        Utiliser ces valeurs
                      </Button>
                      <Button variant="quiet" onClick={reject}>
                        Pas d&apos;accord
                      </Button>
                    </>
                  )
                }
              >
                {!estimate.readable ? (
                  <p>
                    Le modèle ne reconnaît pas de repas là-dedans. Les macros restent à saisir — ou
                    à laisser vides.
                  </p>
                ) : estimate.empty ? (
                  <p>
                    Le modèle n&apos;a rien su estimer. Rien n&apos;a été rempli : mieux vaut un
                    champ vide qu&apos;un chiffre inventé.
                  </p>
                ) : proposed.length > 0 ? (
                  <p>
                    Les champs en pointillé viennent de l&apos;estimation. Corrige-les au doigt : ce
                    que tu retouches devient ta valeur.
                  </p>
                ) : (
                  <p>
                    Ce repas contiendrait <strong>{sentence}</strong>. C&apos;est une estimation,
                    pas une mesure — rien n&apos;est enregistré avant ta validation.
                  </p>
                )}
              </AiBlock>
            ))}

          {/* Pas-à-pas et non champs libres : une valeur proposée doit pouvoir se corriger
              au pouce, sinon elle sera adoptée telle quelle faute de pouvoir la retoucher. */}
          <div className={styles.triple}>
            <Stepper
              label="Protéines (g)"
              value={values.protein_g}
              onChange={setMacro('protein_g')}
              step={5}
              min={0}
              proposed={proposed.includes('protein_g')}
              error={error?.messageFor('protein_g')}
            />
            <Stepper
              label="Sucres (g)"
              value={values.added_sugar_g}
              onChange={setMacro('added_sugar_g')}
              step={5}
              min={0}
              proposed={proposed.includes('added_sugar_g')}
              error={error?.messageFor('added_sugar_g')}
            />
            <Stepper
              label="Calories"
              inputMode="numeric"
              value={values.calories}
              onChange={setMacro('calories')}
              step={50}
              min={0}
              proposed={proposed.includes('calories')}
              error={error?.messageFor('calories')}
            />
          </div>

          <div className={styles.sheetCommit}>
            <Button
              type="submit"
              variant="primary"
              className={cx(styles.commit)}
              busy={save.isPending}
              disabled={nothingToLog || busy}
            >
              Enregistrer le repas
            </Button>
            {/* Revenir en arrière **à n'importe quelle étape**, sans rien écrire. Un
                second appui — la poignée, le voile, Échap — ferme la feuille entière. */}
            <Button variant="quiet" disabled={save.isPending} onClick={reset}>
              Changer de mode
            </Button>
          </div>

          {nothingToLog && (
            <p className={styles.empty}>
              Une photo ou une description suffit. Les macros peuvent attendre.
            </p>
          )}
        </form>
      )}
    </Sheet>
  );
}

/**
 * Écrit un nombre pour un champ de saisie.
 *
 * Sans séparateur de milliers, contrairement à `num` : ce texte repart vers le serveur, et
 * la virgule décimale fait partie du contrat (`ACT-01`).
 */
function fieldText(value: number): string {
  return String(value).replace('.', ',');
}
