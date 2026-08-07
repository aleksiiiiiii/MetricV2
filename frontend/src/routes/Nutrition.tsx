import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';

import {
  AiBlock,
  Badge,
  Button,
  Card,
  Empty,
  Field,
  PageHead,
  Ring,
  Rule,
  Stat,
  Stepper,
} from '@/components/ui';
import { useAiStatus } from '@/features/ai/useAiStatus';
import {
  nutritionApi,
  type Favorite,
  type Meal,
  type MealEstimate,
  type MealFormValues,
} from '@/features/nutrition/api';
import { usePhoto } from '@/features/nutrition/usePhoto';
import { ApiError } from '@/lib/api';
import { cx } from '@/lib/cx';
import { integer, longDate, num, time } from '@/lib/format';
import { CROSS_CUTTING, keys } from '@/lib/query';
import { useToast } from '@/lib/toast';

import styles from './Nutrition.module.css';

const EMPTY_FORM: MealFormValues = {
  meal_type: '',
  comment: '',
  protein_g: '',
  added_sugar_g: '',
  calories: '',
  photo: null,
  source: 'manual',
};

/** Les trois macros qu'une estimation peut proposer, et que l'écran marque comme telles. */
type Macro = 'protein_g' | 'added_sugar_g' | 'calories';

/**
 * Écrit un nombre pour un champ de saisie.
 *
 * Sans séparateur de milliers, contrairement à `num` : ce texte repart vers le serveur, et
 * la virgule décimale fait partie du contrat (`ACT-01`).
 */
function fieldText(value: number | null): string {
  return value === null ? '' : String(value).replace('.', ',');
}

function useInvalidateNutrition() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: keys.nutrition.all() });
    for (const key of CROSS_CUTTING) void client.invalidateQueries({ queryKey: key });
  };
}

// ── Vignette ──────────────────────────────────────────

function Thumbnail({ meal }: { meal: Meal }) {
  const url = usePhoto(meal.photo);

  if (meal.photo === null) return <div className={styles.thumbEmpty} aria-hidden="true" />;
  if (url === null) return <div className={styles.thumbEmpty} aria-hidden="true" />;
  return <img className={styles.thumb} src={url} alt={meal.comment ?? 'Photo du repas'} />;
}

// ── Une ligne du journal ──────────────────────────────

/**
 * Un repas déjà enregistré, et la porte de rattrapage que l'écran promet.
 *
 * « Une photo suffit, les chiffres peuvent venir après » : sans cette porte, « après »
 * n'existerait que pour les repas dont on a encore le fichier d'origine sous la main.
 * L'estimation ne modifie rien par elle-même — elle propose, et c'est un second appui qui
 * écrit, sous garde de jeton comme toute correction (`STO-05`).
 */
function MealCard({
  meal,
  onRemove,
  removing,
}: {
  meal: Meal;
  onRemove: () => void;
  removing: boolean;
}) {
  const invalidate = useInvalidateNutrition();
  const { notify } = useToast();
  const ai = useAiStatus();
  const [estimate, setEstimate] = useState<MealEstimate | null>(null);

  const suggest = useMutation({
    mutationFn: () => nutritionApi.analyzeMeal(meal.id),
    onSuccess: setEstimate,
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Estimation impossible.', 'recover');
    },
  });

  const apply = useMutation({
    mutationFn: (result: MealEstimate) =>
      nutritionApi.update(meal.id, meal.token, {
        meal_type: meal.meal_type,
        comment: meal.comment ?? result.comment,
        protein_g: result.protein_g,
        added_sugar_g: result.added_sugar_g,
        calories: result.calories,
        // La provenance change réellement : ces macros n'ont pas été relevées.
        source: 'ai',
      }),
    onSuccess: () => {
      invalidate();
      setEstimate(null);
      notify('Estimation enregistrée. Elle se corrige comme une saisie.', 'effort');
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Enregistrement impossible.', 'recover');
    },
  });

  // Un repas sans photo n'a rien à faire analyser, et un repas déjà chiffré n'a rien à
  // gagner à l'être : la proposition ne s'affiche que là où elle apporte quelque chose.
  const estimable = ai.enabled && meal.photo !== null && meal.protein_g === null;

  return (
    <div className={styles.meal}>
      <Thumbnail meal={meal} />
      <div className={styles.mealBody}>
        <div className={styles.mealHead}>
          <span className={styles.mealTime}>{time(meal.datetime)}</span>
          <Badge tone="signal">{meal.meal_type}</Badge>
          {meal.source !== 'manual' && <Badge tone="load">{meal.source}</Badge>}
        </div>
        {meal.comment !== null && <div>{meal.comment}</div>}
        <div className={styles.mealMacros}>
          {meal.protein_g !== null ? `${num(meal.protein_g, 0)} g prot.` : 'macros non renseignées'}
          {meal.added_sugar_g !== null && ` · ${num(meal.added_sugar_g, 0)} g sucres`}
          {meal.calories !== null && ` · ${integer(meal.calories)} kcal`}
        </div>

        {estimate !== null && (
          <div className={styles.mealEstimate}>
            <AiBlock
              tag="Estimation"
              actions={
                estimate.empty || !estimate.readable ? (
                  <Button
                    variant="quiet"
                    onClick={() => {
                      setEstimate(null);
                    }}
                  >
                    Fermer
                  </Button>
                ) : (
                  <>
                    <Button
                      variant="primary"
                      busy={apply.isPending}
                      onClick={() => {
                        apply.mutate(estimate);
                      }}
                    >
                      Enregistrer ces valeurs
                    </Button>
                    <Button
                      variant="quiet"
                      onClick={() => {
                        setEstimate(null);
                      }}
                    >
                      Pas d&apos;accord
                    </Button>
                  </>
                )
              }
            >
              {estimate.empty || !estimate.readable ? (
                <p>
                  Rien n&apos;a pu être estimé sur cette photo. Le repas reste tel quel — les macros
                  se saisissent à la main.
                </p>
              ) : (
                <p>
                  Ce repas contiendrait <strong>{estimateSentence(estimate)}</strong>. Rien
                  n&apos;est enregistré tant que tu n&apos;as pas validé.
                </p>
              )}
            </AiBlock>
          </div>
        )}
      </div>

      <div className={styles.mealActions}>
        {estimable && estimate === null && (
          <button
            type="button"
            className={styles.iconButton}
            aria-label={`Estimer les macros du repas de ${time(meal.datetime)}`}
            disabled={suggest.isPending}
            onClick={() => {
              suggest.mutate();
            }}
          >
            {suggest.isPending ? '…' : 'estimer'}
          </button>
        )}
        <button
          type="button"
          className={cx(styles.iconButton, styles.danger)}
          aria-label={`Supprimer le repas de ${time(meal.datetime)}`}
          disabled={removing}
          onClick={onRemove}
        >
          supprimer
        </button>
      </div>
    </div>
  );
}

// ── Saisie ────────────────────────────────────────────

/**
 * Ce que le modèle propose, en une phrase lisible.
 *
 * Écrit ici et non dans un composant : c'est du formatage, et il n'y a rien à calculer —
 * les nombres arrivent tels que le serveur les a relus et bornés.
 */
function estimateSentence(estimate: MealEstimate): string {
  const parts: string[] = [];
  if (estimate.protein_g !== null) parts.push(`${num(estimate.protein_g, 0)} g de protéines`);
  if (estimate.added_sugar_g !== null)
    parts.push(`${num(estimate.added_sugar_g, 0)} g de sucres ajoutés`);
  if (estimate.calories !== null) parts.push(`${integer(estimate.calories)} kcal`);

  if (parts.length === 0) return '';
  if (parts.length === 1) return parts[0] ?? '';
  return `${parts.slice(0, -1).join(', ')} et ${parts[parts.length - 1] ?? ''}`;
}

function MealForm({ suggested, types }: { suggested: string; types: string[] }) {
  const invalidate = useInvalidateNutrition();
  const { notify } = useToast();
  const ai = useAiStatus();
  const fileInput = useRef<HTMLInputElement>(null);

  const [values, setValues] = useState<MealFormValues>(EMPTY_FORM);
  const [preview, setPreview] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  // Ce que le modèle a proposé, et lesquelles de ces valeurs sont encore les siennes.
  // Deux états et non un : une valeur retouchée cesse d'être une proposition, mais
  // l'estimation reste affichée — elle explique d'où vient ce qui est dans les champs.
  const [estimate, setEstimate] = useState<MealEstimate | null>(null);
  const [proposed, setProposed] = useState<Macro[]>([]);

  // L'aperçu est créé au moment du choix et non dans un effet : c'est là que le fichier
  // change, et l'ancienne URL doit être révoquée à ce moment précis.
  function choose(file: File | null) {
    setPreview((current) => {
      if (current) URL.revokeObjectURL(current);
      return file ? URL.createObjectURL(file) : null;
    });
    setValues((current) => ({ ...current, photo: file }));
    // Une estimation appartient à la photo qui l'a produite : changer de photo sans la
    // jeter laisserait des macros d'une autre assiette.
    reject();
  }

  /**
   * « Pas d'accord » — et l'action fait vraiment ce qu'elle dit.
   *
   * Les valeurs **encore proposées** sont vidées, celles que l'utilisateur a retouchées
   * restent : elles sont à lui. La provenance retombe sur `manual`, sans quoi le fichier
   * dirait « ai » sur un repas dont l'estimation a été refusée.
   */
  function reject() {
    setValues((current) => {
      const cleared = { ...current, source: 'manual' as const };
      for (const macro of proposed) cleared[macro] = '';
      return cleared;
    });
    setProposed([]);
    setEstimate(null);
  }

  const suggest = useMutation({
    mutationFn: (photo: File) => nutritionApi.analyze(photo),
    onSuccess: (result) => {
      setEstimate(result);
    },
    onError: (caught: unknown) => {
      // Un refus de l'IA se dit et s'oublie : le formulaire reste intégralement
      // utilisable à la main (`IA-07`).
      notify(caught instanceof ApiError ? caught.message : 'Estimation impossible.', 'recover');
    },
  });

  /** Applique la proposition aux champs, et retient lesquels en viennent (`NUT-04`). */
  function accept(result: MealEstimate) {
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

  // Révocation au démontage : sans elle, quitter l'écran avec un aperçu ouvert fuirait
  // sa mémoire jusqu'au rechargement.
  useEffect(() => {
    if (preview === null) return;
    return () => {
      URL.revokeObjectURL(preview);
    };
  }, [preview]);

  const save = useMutation({
    mutationFn: () => nutritionApi.create({ ...values, meal_type: values.meal_type || suggested }),
    onSuccess: () => {
      invalidate();
      notify('Repas enregistré.', 'effort');
      setValues(EMPTY_FORM);
      setPreview(null);
      if (fileInput.current) fileInput.current.value = '';
      setError(null);
      setEstimate(null);
      setProposed([]);
    },
    onError: (caught: unknown) => {
      setError(caught instanceof ApiError ? caught : null);
    },
  });

  const set = (name: keyof MealFormValues) => (event: { target: { value: string } }) => {
    setValues((current) => ({ ...current, [name]: event.target.value }));
  };

  /** Correction d'une macro au doigt. Retoucher une proposition la fait sienne. */
  const setMacro = (name: Macro) => (value: string) => {
    setValues((current) => ({ ...current, [name]: value }));
    setProposed((current) => current.filter((macro) => macro !== name));
  };

  const nothingToLog = values.comment.trim() === '' && values.photo === null;
  const sentence = estimate === null ? '' : estimateSentence(estimate);

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

      <div className={styles.field}>
        <label htmlFor="meal-type">Type</label>
        <select
          id="meal-type"
          className={styles.select}
          value={values.meal_type || suggested}
          onChange={set('meal_type')}
        >
          {types.map((type) => (
            <option value={type} key={type}>
              {type}
            </option>
          ))}
        </select>
      </div>

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
            choose(event.target.files?.[0] ?? null);
          }}
        />
        {preview !== null ? (
          <img className={styles.preview} src={preview} alt="Aperçu du repas" />
        ) : (
          <label htmlFor="meal-photo" className={styles.drop}>
            prendre ou choisir une photo
          </label>
        )}
      </div>

      {/* Lecture assistée (`NUT-04`). Le bloc n'apparaît qu'avec une photo : sans image,
          il n'y a rien à estimer, et un bouton inerte n'apprend rien.
          Sans clé, il n'apparaît pas du tout — et le formulaire est complet sans lui. */}
      {ai.enabled && values.photo !== null && (
        <>
          {estimate === null ? (
            <Button
              variant="ghost"
              busy={suggest.isPending}
              onClick={() => {
                if (values.photo !== null) suggest.mutate(values.photo);
              }}
            >
              Estimer les macros depuis la photo
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
                  Le modèle ne reconnaît pas de nourriture sur cette photo. Les macros restent à
                  saisir — ou à laisser vides.
                </p>
              ) : estimate.empty ? (
                <p>
                  Le modèle n&apos;a rien su estimer sur cette photo. Rien n&apos;a été rempli :
                  mieux vaut un champ vide qu&apos;un chiffre inventé.
                </p>
              ) : proposed.length > 0 ? (
                <p>
                  Les champs en pointillé viennent de l&apos;estimation. Corrige-les au doigt : ce
                  que tu retouches devient ta valeur.
                </p>
              ) : (
                <p>
                  Cette assiette contiendrait <strong>{sentence}</strong>. C&apos;est une lecture
                  d&apos;image, pas une mesure — rien n&apos;est enregistré avant ta validation.
                </p>
              )}
            </AiBlock>
          )}
        </>
      )}

      <Field
        label="Description"
        placeholder="poulet, riz, brocolis"
        value={values.comment}
        error={error?.messageFor('comment')}
        onChange={set('comment')}
      />

      {/* Pas-à-pas et non champs libres : une valeur proposée doit pouvoir se corriger au
          pouce, sinon elle sera adoptée telle quelle faute de pouvoir la retoucher. */}
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

      <Button type="submit" variant="primary" busy={save.isPending} disabled={nothingToLog}>
        Enregistrer le repas
      </Button>
      <p className={styles.empty}>
        Une photo ou une description suffit. Les macros peuvent attendre.
      </p>
    </form>
  );
}

// ── Favoris ───────────────────────────────────────────

function Favorites({ favorites }: { favorites: Favorite[] }) {
  const invalidate = useInvalidateNutrition();
  const { notify } = useToast();
  const [name, setName] = useState('');
  const [protein, setProtein] = useState('');
  const [calories, setCalories] = useState('');

  const add = useMutation({
    mutationFn: () =>
      nutritionApi.addFavorite({
        name,
        protein_g: protein ? Number.parseFloat(protein.replace(',', '.')) : null,
        calories: calories ? Number.parseInt(calories, 10) : null,
      }),
    onSuccess: () => {
      invalidate();
      notify('Repas favori enregistré.', 'signal');
      setName('');
      setProtein('');
      setCalories('');
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Ajout impossible.', 'recover');
    },
  });

  const replay = useMutation({
    mutationFn: (favorite: Favorite) => nutritionApi.replayFavorite(favorite.favorite_id),
    onSuccess: (meal) => {
      invalidate();
      notify(`« ${meal.comment ?? 'Repas'} » ajouté au journal.`, 'effort');
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Rejeu impossible.', 'recover');
    },
  });

  const remove = useMutation({
    mutationFn: (favorite: Favorite) => nutritionApi.removeFavorite(favorite.id, favorite.token),
    onSuccess: () => {
      invalidate();
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Retrait impossible.', 'recover');
    },
  });

  return (
    <Card>
      <h3>Repas récurrents</h3>
      <p className={styles.note}>
        Ce qui revient chaque jour se rejoue en une action, sans photo ni estimation.
      </p>

      {favorites.length > 0 && (
        <div className={styles.favorites}>
          {favorites.map((favorite) => (
            <div className={styles.favorite} key={favorite.favorite_id}>
              <span>
                {favorite.name}
                <br />
                <span className={styles.favoriteMacros}>
                  {favorite.protein_g !== null ? `${num(favorite.protein_g, 0)} g prot.` : '—'}
                  {favorite.calories !== null && ` · ${integer(favorite.calories)} kcal`}
                </span>
              </span>
              <button
                type="button"
                className={styles.iconButton}
                aria-label={`Rejouer ${favorite.name}`}
                onClick={() => {
                  replay.mutate(favorite);
                }}
              >
                rejouer
              </button>
              <button
                type="button"
                className={cx(styles.iconButton, styles.danger)}
                aria-label={`Retirer ${favorite.name}`}
                onClick={() => {
                  remove.mutate(favorite);
                }}
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}

      <form
        className={styles.form}
        onSubmit={(event) => {
          event.preventDefault();
          add.mutate();
        }}
        noValidate
      >
        <Field
          label="Nom"
          placeholder="Skyr + flocons"
          value={name}
          onChange={(event) => {
            setName(event.target.value);
          }}
        />
        <div className={styles.triple}>
          <Field
            label="Protéines"
            inputMode="decimal"
            value={protein}
            onChange={(event) => {
              setProtein(event.target.value);
            }}
          />
          <Field
            label="Calories"
            inputMode="numeric"
            value={calories}
            onChange={(event) => {
              setCalories(event.target.value);
            }}
          />
        </div>
        <Button type="submit" variant="ghost" busy={add.isPending} disabled={name.trim() === ''}>
          Enregistrer comme récurrent
        </Button>
      </form>
    </Card>
  );
}

// ── Écran ─────────────────────────────────────────────

export function Nutrition() {
  const invalidate = useInvalidateNutrition();
  const { notify } = useToast();

  const { data, isPending } = useQuery({
    queryKey: keys.nutrition.all(),
    queryFn: () => nutritionApi.day(),
  });

  const remove = useMutation({
    mutationFn: (meal: Meal) => nutritionApi.remove(meal.id, meal.token),
    onSuccess: () => {
      invalidate();
      notify('Repas supprimé. La photo reste sur Nextcloud.', 'signal');
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Suppression impossible.', 'recover');
      invalidate();
    },
  });

  const totals = data?.totals;

  return (
    <div className="wrap">
      {/* Le jour vient du serveur, dans le fuseau local. Cette ligne écrivait
          `longDate(new Date())` : l'horloge du téléphone, qui n'est pas celle qui a daté
          les repas. Un utilisateur en déplacement, ou éveillé à minuit passé, lisait une
          date qui ne correspondait à aucun des repas affichés dessous. */}
      <PageHead eyebrow="Domaine Nutrition" title="Repas du jour">
        {data !== undefined ? longDate(data.date) : '—'}
      </PageHead>

      <Rule>Totaux</Rule>
      <div className="grid g3">
        <Card>
          {totals && (
            <Ring
              ratio={totals.protein_ratio}
              label="Protéines"
              detail={`${num(totals.protein_g, 0)} g sur ${num(totals.protein_target_g, 0)} g`}
              tone={totals.protein_ratio >= 1 ? 'effort' : 'signal'}
            />
          )}
        </Card>
        <Card>
          <Stat
            label="Sucres ajoutés"
            value={totals ? num(totals.added_sugar_g, 0) : '—'}
            unit={totals ? 'g' : undefined}
            detail={
              totals
                ? totals.over_sugar
                  ? `plafond dépassé (${num(totals.added_sugar_max_g, 0)} g)`
                  : `plafond ${num(totals.added_sugar_max_g, 0)} g`
                : undefined
            }
            direction={totals?.over_sugar === true ? 'down' : undefined}
          />
        </Card>
        <Card>
          <Stat
            label="Calories"
            value={totals && totals.calories > 0 ? integer(totals.calories) : '—'}
            unit={totals && totals.calories > 0 ? 'kcal' : undefined}
            detail={
              totals
                ? totals.calories_known < totals.meals
                  ? `sur ${totals.calories_known} repas renseigné(s) / ${totals.meals}`
                  : `${totals.meals} repas`
                : undefined
            }
          />
        </Card>
      </div>

      <Rule>Journal</Rule>
      <div className={styles.split}>
        <Card>
          {isPending ? (
            <p className={styles.empty}>chargement…</p>
          ) : data && data.meals.length > 0 ? (
            data.meals.map((meal) => (
              <MealCard
                key={`${meal.id}-${meal.token}`}
                meal={meal}
                onRemove={() => {
                  remove.mutate(meal);
                }}
                removing={remove.isPending}
              />
            ))
          ) : (
            <Empty title="Aucun repas aujourd'hui">
              Une photo suffit. Les chiffres peuvent venir après.
            </Empty>
          )}
        </Card>

        <div className="stack">
          <Card>
            <h3>Ajouter un repas</h3>
            {data && <MealForm suggested={data.suggested_type} types={data.types} />}
          </Card>

          <Favorites favorites={data?.favorites ?? []} />
        </div>
      </div>
    </div>
  );
}
