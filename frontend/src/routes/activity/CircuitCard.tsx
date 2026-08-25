/**
 * Une séance Cadence, telle qu'elle se lit et se lance — **la seule implémentation**.
 *
 * Elle sert à trois endroits : en tête de `/activite`, sur `/activite/seances`, et dans le
 * fil de l'assistant. Trois copies auraient donné trois façons de dire « Fait », trois
 * arrondis de durée, et le jour où l'une change les deux autres mentent.
 *
 * ── Ce que la carte ne calcule pas ────────────────────────────────────────
 *
 * Ni le lien, ni la durée. `url` arrive fabriqué par le serveur, `estimated_duration_min`
 * arrive calculée. La carte pose l'un dans un `href` et formate l'autre — avec le `~` que
 * lui impose `exact`, parce qu'une séance en répétitions n'a pas de durée connue.
 *
 * ── « Fait » est un ajout, pas une destruction ────────────────────────────
 *
 * Un appui déplie la durée, un second la consigne. Ce n'est pas une confirmation : c'est
 * la valeur qu'on vient corriger. L'estimation est **proposée**, jamais écrite en silence
 * — sur une séance en répétitions, personne ne connaît la durée réelle, et l'inventer la
 * ferait entrer dans le volume hebdomadaire.
 */

import { useMutation } from '@tanstack/react-query';
import { useState } from 'react';
import type { ReactNode } from 'react';

import { Badge, Button, ExternalLinkButton, Field } from '@/components/ui';
import { IconCheck } from '@/components/ui/icons';
import { activityApi, type Circuit } from '@/features/activity/api';
import { ApiError } from '@/lib/api';
import { celebrate } from '@/lib/confetti';
import { plural } from '@/lib/format';
import { useToast } from '@/lib/toast';

import styles from '../Activity.module.css';
import { circuitDetail, circuitDuration, useInvalidateActivity } from './shared';

export function CircuitCard({
  circuit,
  actions,
}: {
  circuit: Circuit;
  /** Les gestes propres à l'écran hôte — corriger, supprimer. Absents en tête d'écran. */
  actions?: ReactNode;
}) {
  const invalidate = useInvalidateActivity();
  const { notify } = useToast();
  const [logging, setLogging] = useState(false);
  const [minutes, setMinutes] = useState('');

  const done = useMutation({
    mutationFn: () =>
      activityApi.completeCircuit(circuit.id, {
        duration_min: Number(minutes.replace(',', '.')),
      }),
    onSuccess: () => {
      setLogging(false);
      invalidate();
      celebrate();
      notify(`« ${circuit.name} » consignée au journal.`, 'effort');
    },
    onError: (caught: unknown) => {
      notify(caught instanceof ApiError ? caught.message : 'Enregistrement impossible.', 'recover');
    },
  });

  return (
    <>
      <div className={styles.catalogueBody}>
        <div className={styles.catalogueHead}>
          <span>{circuit.name}</span>
          <Badge tone="signal">{circuitDuration(circuit)}</Badge>
        </div>
        <span className={styles.circuitMeta}>
          {circuit.rounds} {plural(circuit.rounds, 'round')} · {circuit.exercises.length}{' '}
          {plural(circuit.exercises.length, 'exercice')}
        </span>
        <span className={styles.entryDetail}>{circuitDetail(circuit)}</span>

        {logging && (
          <div className={styles.circuitDone}>
            <Field
              label={`Durée réelle de ${circuit.name} (min)`}
              inputMode="decimal"
              value={minutes}
              hint={
                circuit.exact
                  ? 'Durée calculée de la séance'
                  : 'Estimation : la séance contient des répétitions'
              }
              onChange={(event) => {
                setMinutes(event.target.value);
              }}
            />
            <div className={styles.sheetCommit}>
              <Button
                variant="primary"
                className={styles.commit}
                busy={done.isPending}
                disabled={minutes.trim() === ''}
                onClick={() => {
                  done.mutate();
                }}
              >
                Consigner au journal
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* Deux rangées : « Ouvrir » est l'action qui **termine** le geste, elle prend la
          largeur du bloc et sa hauteur `--tap-lg`. Les autres restent des pastilles.

          Le bloc existe parce qu'au-delà de 600 px la rangée passe en `flex-direction:
          row` : un lien en `width: 100 %` posé là en frère du texte recouvrait le nom. */}
      <div className={styles.circuitActions}>
        {circuit.url !== null && (
          <ExternalLinkButton
            variant="primary"
            className={styles.circuitOpen}
            href={circuit.url}
            aria-label={`Ouvrir ${circuit.name} dans Cadence`}
          >
            Ouvrir dans Cadence
          </ExternalLinkButton>
        )}

        <div className={styles.catalogueActions}>
          {/* « Fait » tout court se lisait comme une étiquette d'état — « cette séance
              est faite » — au lieu d'un geste. La coche et le verbe disent qu'on agit, et
              le mot reste court : la carte en porte trois autres à côté. */}
          <Button
            variant="ghost"
            className={styles.circuitDoneBtn}
            aria-label={`Déclarer ${circuit.name} faite`}
            aria-expanded={logging}
            onClick={() => {
              setLogging((current) => !current);
              setMinutes(String(Math.round(circuit.estimated_duration_min)));
            }}
          >
            <IconCheck size={18} />
            {logging ? 'Annuler' : 'Je l’ai faite'}
          </Button>
          {actions}
        </div>
      </div>
    </>
  );
}
