/**
 * Les séances Cadence, **en tête de `/activite`**.
 *
 * ── Pourquoi elles passent devant ─────────────────────────────────────────
 *
 * L'écran a déjà son principe : ce qu'on **fait** passe devant ce qu'on lit, et le journal
 * est passé devant les statistiques pour cette raison. Une séance Cadence est le geste le
 * plus direct de l'écran — un appui et elle démarre — alors que consigner une série suppose
 * d'avoir déjà commencé. Elle prend donc la première place.
 *
 * ── Ce que la section ne fait pas ─────────────────────────────────────────
 *
 * Ni créer, ni corriger, ni supprimer : tout ça vit sur `/activite/seances`, qui a l'espace
 * et l'adresse. Ici on ouvre et on consigne — les deux gestes qu'on fait le téléphone à la
 * main, entre deux exercices. Une section qui porterait le formulaire entier ramènerait le
 * défaut que la page a précisément corrigé.
 *
 * ── Trois, et pas la liste entière ────────────────────────────────────────
 *
 * Au-delà, la section repousse le journal hors de l'écran et redevient un catalogue. Trois
 * cartes tiennent au-dessus de la ligne de flottaison d'un iPhone, et le lien mène au
 * reste.
 */

import { useQuery } from '@tanstack/react-query';

import { Card, Empty, LinkButton, Rule } from '@/components/ui';
import { activityApi } from '@/features/activity/api';
import { keys } from '@/lib/query';

import styles from '../Activity.module.css';
import { CircuitCard } from './CircuitCard';

/** Combien de séances tiennent en tête d'écran sans repousser le journal. */
const SHOWN = 3;

export function CircuitsSection() {
  const { data, isPending, error } = useQuery({
    queryKey: keys.activity.circuits(),
    queryFn: activityApi.circuits,
  });

  const circuits = data?.circuits ?? [];
  const shown = circuits.slice(0, SHOWN);

  return (
    <>
      <Rule>Séances Cadence</Rule>

      <Card>
        {error !== null ? (
          // Le message vient du serveur, en français. Une section en panne ne doit pas
          // emporter l'écran : le journal, lui, s'affiche toujours en dessous.
          <p className={styles.error} role="alert">
            {error instanceof Error ? error.message : 'Séances illisibles.'}
          </p>
        ) : isPending ? (
          <p className={styles.empty}>chargement…</p>
        ) : circuits.length === 0 ? (
          <Empty title="Aucune séance">
            Une séance construite une fois s’ouvre ensuite d’un appui, et se consigne au journal
            quand elle est faite.
          </Empty>
        ) : (
          <ul className={styles.catalogue} aria-label="Séances Cadence">
            {shown.map((circuit) => (
              <li className={styles.catalogueRow} key={circuit.circuit_id || circuit.id}>
                <CircuitCard circuit={circuit} />
              </li>
            ))}
          </ul>
        )}

        <div className={styles.circuitMore}>
          <LinkButton to="/activite/seances">
            {circuits.length > SHOWN
              ? `Toutes les séances (${String(circuits.length)})`
              : 'Créer une séance'}
          </LinkButton>
          {/* La composition assistée, à côté du formulaire et non à sa place : les deux
              mènent au même enregistrement, et celui qui sait déjà ce qu'il veut n'a pas à
              passer par un modèle pour l'écrire. */}
          <LinkButton variant="quiet" to="/activite/creer">
            Composer avec l’assistant
          </LinkButton>
        </div>
      </Card>
    </>
  );
}
