import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';

import { Badge, Button, Card, Empty, Field, Ring, Rule, Stat } from '@/components/ui';
import {
  nutritionApi,
  type Favorite,
  type Meal,
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
};

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

// ── Saisie ────────────────────────────────────────────

function MealForm({ suggested, types }: { suggested: string; types: string[] }) {
  const invalidate = useInvalidateNutrition();
  const { notify } = useToast();
  const fileInput = useRef<HTMLInputElement>(null);

  const [values, setValues] = useState<MealFormValues>(EMPTY_FORM);
  const [preview, setPreview] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  // L'aperçu est créé au moment du choix et non dans un effet : c'est là que le fichier
  // change, et l'ancienne URL doit être révoquée à ce moment précis.
  function choose(file: File | null) {
    setPreview((current) => {
      if (current) URL.revokeObjectURL(current);
      return file ? URL.createObjectURL(file) : null;
    });
    setValues((current) => ({ ...current, photo: file }));
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
    },
    onError: (caught: unknown) => {
      setError(caught instanceof ApiError ? caught : null);
    },
  });

  const set = (name: keyof MealFormValues) => (event: { target: { value: string } }) => {
    setValues((current) => ({ ...current, [name]: event.target.value }));
  };

  const nothingToLog = values.comment.trim() === '' && values.photo === null;

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

      <Field
        label="Description"
        placeholder="poulet, riz, brocolis"
        value={values.comment}
        error={error?.messageFor('comment')}
        onChange={set('comment')}
      />

      <div className={styles.triple}>
        <Field
          label="Protéines (g)"
          inputMode="decimal"
          value={values.protein_g}
          error={error?.messageFor('protein_g')}
          onChange={set('protein_g')}
        />
        <Field
          label="Sucres (g)"
          inputMode="decimal"
          value={values.added_sugar_g}
          error={error?.messageFor('added_sugar_g')}
          onChange={set('added_sugar_g')}
        />
        <Field
          label="Calories"
          inputMode="numeric"
          value={values.calories}
          error={error?.messageFor('calories')}
          onChange={set('calories')}
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
      <p className="eyebrow">Domaine Nutrition</p>
      <h1 style={{ marginTop: 10 }}>Repas du jour</h1>
      <p className="lede" style={{ marginTop: 14 }}>
        {longDate(new Date())}
      </p>

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
              <div className={styles.meal} key={`${meal.id}-${meal.token}`}>
                <Thumbnail meal={meal} />
                <div className={styles.mealBody}>
                  <div className={styles.mealHead}>
                    <span className={styles.mealTime}>{time(meal.datetime)}</span>
                    <Badge tone="signal">{meal.meal_type}</Badge>
                    {meal.source !== 'manual' && <Badge tone="load">{meal.source}</Badge>}
                  </div>
                  {meal.comment !== null && <div>{meal.comment}</div>}
                  <div className={styles.mealMacros}>
                    {meal.protein_g !== null
                      ? `${num(meal.protein_g, 0)} g prot.`
                      : 'macros non renseignées'}
                    {meal.added_sugar_g !== null && ` · ${num(meal.added_sugar_g, 0)} g sucres`}
                    {meal.calories !== null && ` · ${integer(meal.calories)} kcal`}
                  </div>
                </div>
                <div className={styles.mealActions}>
                  <button
                    type="button"
                    className={cx(styles.iconButton, styles.danger)}
                    aria-label={`Supprimer le repas de ${time(meal.datetime)}`}
                    onClick={() => {
                      remove.mutate(meal);
                    }}
                  >
                    supprimer
                  </button>
                </div>
              </div>
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

      <div style={{ height: 40 }} />
    </div>
  );
}
