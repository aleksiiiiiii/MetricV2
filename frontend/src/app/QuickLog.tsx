/**
 * Saisie rapide — la feuille du bouton central.
 *
 * `LogButton` porte depuis le début le principe du projet : « un relevé en un geste ».
 * Il demandait pourtant d'aller d'abord sur le bon écran, ce qui en fait trois. Cette
 * feuille s'ouvre depuis n'importe où et ramène un relevé à **deux appuis**.
 *
 * **Trois écritures seulement**, et c'est délibéré. Un verre d'eau, un supplément et une
 * pesée sont des gestes à un chiffre — ou à zéro. Un repas et une séance demandent un
 * vrai formulaire : les proposer ici en version réduite donnerait deux façons de saisir
 * la même chose, dont une amputée. Ils sont donc des **liens**, pas des raccourcis.
 *
 * Ce que la feuille ne fait pas :
 *
 * * **Elle ne calcule rien.** Totaux, objectifs et séries viennent du serveur, comme
 *   partout ailleurs.
 * * **Elle ne devine pas la date.** Le jour vient de `checklist().date` — le serveur, dans
 *   le fuseau local. Jamais `new Date()`.
 * * **Elle ne charge rien tant qu'elle est fermée** : les trois requêtes sont conditionnées
 *   à son ouverture, pour qu'un bouton de barre ne coûte pas trois appels à chaque écran.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate } from 'react-router';

import { Button, Chip, ChipStrip, Sheet, SheetGroup, SheetRow, Stepper } from '@/components/ui';
import { IconActivity, IconNutrition } from '@/components/ui/icons';
import { bodyApi } from '@/features/body/api';
import { routineApi } from '@/features/routine/api';
import { ApiError } from '@/lib/api';
import { kg, volume } from '@/lib/format';
import { CROSS_CUTTING, keys } from '@/lib/query';
import { useToast } from '@/lib/toast';

import styles from './QuickLog.module.css';

export function QuickLog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const { notify } = useToast();

  const [weight, setWeight] = useState('');
  const [weightError, setWeightError] = useState<string | undefined>(undefined);

  const hydration = useQuery({
    queryKey: keys.hydration.all(),
    queryFn: () => routineApi.hydration(),
    enabled: open,
  });

  const checklist = useQuery({
    queryKey: keys.supplements.today(),
    queryFn: routineApi.checklist,
    enabled: open,
  });

  const lastWeight = useQuery({
    queryKey: keys.body.weight(),
    queryFn: () => bodyApi.weight(1),
    enabled: open,
  });

  /** Toute écriture rafraîchit son domaine **et** les vues transverses (`HEAT-33`, `AGG-01`). */
  function refresh(domain: readonly unknown[]): void {
    void client.invalidateQueries({ queryKey: domain });
    for (const key of CROSS_CUTTING) void client.invalidateQueries({ queryKey: key });
  }

  const drink = useMutation({
    mutationFn: (milliliters: number) => routineApi.drink(milliliters),
    onSuccess: (_result, milliliters) => {
      refresh(keys.hydration.all());
      notify(`${volume(milliliters)} de plus aujourd’hui.`, 'signal');
    },
    onError: (error: unknown) => {
      notify(error instanceof ApiError ? error.message : 'Enregistrement impossible.', 'recover');
    },
  });

  const take = useMutation({
    mutationFn: (scheduleId: string) => routineApi.take(scheduleId),
    onSuccess: () => {
      refresh(keys.supplements.all());
    },
    onError: (error: unknown) => {
      notify(error instanceof ApiError ? error.message : 'Enregistrement impossible.', 'recover');
    },
  });

  const logWeight = useMutation({
    mutationFn: (payload: { date: string; weight_kg: number }) => bodyApi.createWeight(payload),
    onSuccess: () => {
      refresh(keys.body.all());
      notify('Pesée enregistrée.', 'effort');
      setWeight('');
      setWeightError(undefined);
      onClose();
    },
    onError: (error: unknown) => {
      // Le texte vient du serveur, en français, et s'affiche tel quel (`API-06`).
      setWeightError(error instanceof ApiError ? error.message : 'Enregistrement impossible.');
    },
  });

  // Le jour vient du serveur — le seul endroit où cette feuille peut le lire.
  const today = checklist.data?.date ?? null;
  const pending = checklist.data?.items.filter((item) => !item.taken) ?? [];
  const presets = hydration.data?.presets_ml ?? [];
  const latestKg = lastWeight.data?.stats.latest_kg ?? null;

  function submitWeight(): void {
    if (today === null) return;
    const parsed = Number(weight.trim().replace(',', '.'));
    if (!Number.isFinite(parsed) || parsed <= 0) {
      setWeightError('Un poids en kilogrammes, par exemple 82,4.');
      return;
    }
    logWeight.mutate({ date: today, weight_kg: parsed });
  }

  function go(path: string): void {
    onClose();
    void navigate(path);
  }

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Noter"
      lede="Ce qui tient en un chiffre s’enregistre ici, sans changer d’écran."
    >
      <SheetGroup title="Hydratation">
        {hydration.isPending ? (
          <p className={styles.wait}>chargement…</p>
        ) : presets.length === 0 ? (
          <p className={styles.wait}>Aucun format enregistré.</p>
        ) : (
          <>
            <ChipStrip label="Volumes d’un verre">
              {presets.map((milliliters) => (
                <Chip
                  key={milliliters}
                  disabled={drink.isPending}
                  onClick={() => {
                    drink.mutate(milliliters);
                  }}
                >
                  + {volume(milliliters)}
                </Chip>
              ))}
            </ChipStrip>
            {hydration.data !== undefined && (
              <p className={styles.tally}>
                <b className="num">{volume(hydration.data.stats.today_ml)}</b> aujourd’hui, objectif{' '}
                <b className="num">{volume(hydration.data.stats.target_ml)}</b>
              </p>
            )}
          </>
        )}
      </SheetGroup>

      {pending.length > 0 && (
        <SheetGroup title="Suppléments à prendre">
          {pending.map((item) => (
            <SheetRow
              key={item.schedule_id}
              label={item.name}
              hint={`${String(item.dose)} ${item.unit} · ${item.time}`}
              onClick={() => {
                take.mutate(item.schedule_id);
              }}
            />
          ))}
        </SheetGroup>
      )}

      <SheetGroup title="Pesée">
        <Stepper
          label="Poids du matin"
          value={weight}
          onChange={(next) => {
            setWeight(next);
            setWeightError(undefined);
          }}
          step={0.1}
          min={20}
          max={400}
          placeholder={latestKg !== null ? kg(latestKg) : '—'}
          {...(weightError !== undefined ? { error: weightError } : {})}
          hint={
            latestKg !== null
              ? `dernière pesée ${kg(latestKg)}`
              : 'Un chiffre, et la courbe commence.'
          }
        />
        <div className={styles.confirm}>
          <Button
            variant="primary"
            className={styles.save}
            busy={logWeight.isPending}
            disabled={weight.trim() === '' || today === null}
            onClick={submitWeight}
          >
            Enregistrer la pesée
          </Button>
        </div>
      </SheetGroup>

      <SheetGroup title="Ce qui demande un formulaire">
        <SheetRow
          icon={<IconNutrition size={20} />}
          label="Ajouter un repas"
          hint="→"
          onClick={() => {
            go('/nutrition');
          }}
        />
        <SheetRow
          icon={<IconActivity size={20} />}
          label="Noter une séance"
          hint="→"
          onClick={() => {
            go('/activite');
          }}
        />
      </SheetGroup>
    </Sheet>
  );
}
