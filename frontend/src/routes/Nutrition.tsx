/**
 * Écran Nutrition — les repas du jour, leurs totaux, et de quoi en ajouter un.
 *
 * **Le formulaire a quitté la page.** Il était déplié en permanence sous le journal :
 * un type, une photo, une description et trois pas-à-pas, qu'on vienne photographier son
 * assiette ou taper trois nombres. Il vit maintenant dans une feuille qui demande d'abord
 * **comment** on veut noter — [MealSheet](./nutrition/MealSheet.tsx).
 *
 * Ce qui reste ici se lit : les totaux, le journal, et les repas récurrents.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

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
} from '@/components/ui';
import { useAiStatus } from '@/features/ai/useAiStatus';
import {
  nutritionApi,
  type Favorite,
  type Meal,
  type MealEstimate,
} from '@/features/nutrition/api';
import { usePhoto } from '@/features/nutrition/usePhoto';
import { ApiError } from '@/lib/api';
import { cx } from '@/lib/cx';
import { integer, longDate, num, plural, time } from '@/lib/format';
import { CROSS_CUTTING, keys } from '@/lib/query';
import { useToast } from '@/lib/toast';

import styles from './Nutrition.module.css';
import { estimateSentence } from './nutrition/estimate';
import { MealSheet } from './nutrition/MealSheet';

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

// ── Repas récurrents ──────────────────────────────────

/**
 * Ce qui revient chaque jour, rejoué en une action.
 *
 * **Les sucres manquaient.** Le fichier les porte depuis toujours — `favorites.csv` a la
 * colonne, le schéma la valide, le service la relit —, mais la carte ne les demandait pas
 * et ne les affichait pas. Un repas récurrent enregistré ici arrivait donc au journal avec
 * ses protéines et ses calories, et un sucre à vide : le plafond quotidien comptait faux
 * pour tout ce qui se rejoue.
 */
function Favorites({ favorites }: { favorites: Favorite[] }) {
  const invalidate = useInvalidateNutrition();
  const { notify } = useToast();
  const [name, setName] = useState('');
  const [protein, setProtein] = useState('');
  const [sugar, setSugar] = useState('');
  const [calories, setCalories] = useState('');
  const [armed, setArmed] = useState<number | null>(null);

  /** Un champ de texte vers le nombre que l'API attend, ou `null` s'il est vide. */
  function decimal(value: string): number | null {
    const cleaned = value.replace(',', '.').trim();
    if (cleaned === '') return null;
    const parsed = Number.parseFloat(cleaned);
    return Number.isFinite(parsed) ? parsed : null;
  }

  const add = useMutation({
    mutationFn: () =>
      nutritionApi.addFavorite({
        name,
        protein_g: decimal(protein),
        added_sugar_g: decimal(sugar),
        calories: decimal(calories) === null ? null : Math.round(decimal(calories) ?? 0),
      }),
    onSuccess: () => {
      invalidate();
      notify('Repas favori enregistré.', 'signal');
      setName('');
      setProtein('');
      setSugar('');
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
      setArmed(null);
      invalidate();
    },
    onError: (caught: unknown) => {
      setArmed(null);
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
                  {favorite.added_sugar_g !== null &&
                    ` · ${num(favorite.added_sugar_g, 0)} g sucres`}
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
              {/* Deux appuis pour détruire : le projet n'a pas d'annulation. Et un
                  libellé plutôt qu'un « ✕ » — le glyphe faisait une cible de 25 px de
                  large, et « retirer » dit ce qu'il fait. */}
              <button
                type="button"
                className={cx(
                  styles.iconButton,
                  styles.danger,
                  armed === favorite.id && styles.armed,
                )}
                aria-label={
                  armed === favorite.id
                    ? `Retirer ${favorite.name} — confirmer`
                    : `Retirer ${favorite.name}`
                }
                disabled={remove.isPending}
                onClick={() => {
                  if (armed !== favorite.id) {
                    setArmed(favorite.id);
                    return;
                  }
                  remove.mutate(favorite);
                }}
              >
                {armed === favorite.id ? 'confirmer ?' : 'retirer'}
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
        {/* Les trois macros, au même rang. Les sucres n'étaient pas là, et le plafond
            quotidien comptait donc faux sur tout ce qui se rejoue. */}
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
            label="Sucres"
            inputMode="decimal"
            value={sugar}
            onChange={(event) => {
              setSugar(event.target.value);
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
  const [adding, setAdding] = useState(false);

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
    <div className={cx('wrap', styles.screen)}>
      {/* Le jour vient du serveur, dans le fuseau local. Cette ligne écrivait
          `longDate(new Date())` : l'horloge du téléphone, qui n'est pas celle qui a daté
          les repas. */}
      <PageHead
        eyebrow="Domaine Nutrition"
        title="Repas du jour"
        actions={
          <Button
            variant="primary"
            disabled={data === undefined}
            onClick={() => {
              setAdding(true);
            }}
          >
            Ajouter un repas
          </Button>
        }
      >
        {data !== undefined ? longDate(data.date) : '—'}
      </PageHead>

      {/* Les trois totaux d'une même journée disaient zéro de trois façons : « 0 % » dans
          l'anneau, « 0 g » pour les sucres, « — » pour les calories. Sans repas, il n'y a
          pas trois états — il n'y en a qu'un, et c'est le tiret. */}
      <Rule>Totaux</Rule>
      <Card>
        {totals && (
          <Ring
            ratio={totals.meals > 0 ? totals.protein_ratio : null}
            label="Protéines"
            detail={
              totals.meals > 0
                ? `${num(totals.protein_g, 0)} g sur ${num(totals.protein_target_g, 0)} g`
                : `objectif ${num(totals.protein_target_g, 0)} g`
            }
            tone={totals.protein_ratio >= 1 ? 'effort' : 'signal'}
          />
        )}
      </Card>

      {/* Deux tuiles : un libellé, un chiffre, une ligne. Elles tiennent de front. */}
      <div className="grid tiles">
        <Card>
          <Stat
            compact
            label="Sucres ajoutés"
            value={totals && totals.meals > 0 ? num(totals.added_sugar_g, 0) : '—'}
            unit={totals && totals.meals > 0 ? 'g' : undefined}
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
            compact
            label="Calories"
            value={totals && totals.calories > 0 ? integer(totals.calories) : '—'}
            unit={totals && totals.calories > 0 ? 'kcal' : undefined}
            detail={
              totals
                ? totals.calories_known < totals.meals
                  ? `sur ${totals.calories_known} repas ${plural(totals.calories_known, 'renseigné')} / ${totals.meals}`
                  : `${integer(totals.meals)} repas`
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

        <Favorites favorites={data?.favorites ?? []} />
      </div>

      {data !== undefined && (
        <MealSheet
          open={adding}
          suggested={data.suggested_type}
          types={data.types}
          onClose={() => {
            setAdding(false);
          }}
          onSaved={() => {
            setAdding(false);
            invalidate();
          }}
        />
      )}
    </div>
  );
}
