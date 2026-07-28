import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { Badge, Button, Card, Empty, Field, Rule } from '@/components/ui';
import {
  settingsApi,
  type SettingsPayload,
  type SettingsValues,
  type SettingsView,
} from '@/features/settings/api';
import { ApiError } from '@/lib/api';
import { num } from '@/lib/format';
import { CROSS_CUTTING, keys } from '@/lib/query';
import { useToast } from '@/lib/toast';

import styles from './Settings.module.css';

/**
 * Les réglages généralistes (`L08-08`).
 *
 * Les pistes d'assiduité — création, cadence, seuils — viendront au lot L11 : elles
 * n'existent pas encore comme données, et leur inventer une section vide ici ne
 * renseignerait personne.
 *
 * Un principe tient tout l'écran : **aucune valeur de repli n'est écrite côté client.**
 * Les défauts arrivent du serveur avec les valeurs effectives, et l'écran se contente de
 * dire lequel des deux il affiche.
 */

interface FieldSpec {
  key: keyof SettingsValues;
  label: string;
  hint: string;
  unit: string;
}

const NUMBERS: readonly FieldSpec[] = [
  {
    key: 'target_weight_kg',
    label: 'Poids cible',
    hint: 'Écart restant sur le tableau de bord',
    unit: 'kg',
  },
  {
    key: 'target_protein_g',
    label: 'Protéines par jour',
    hint: 'Anneau de l’écran Nutrition',
    unit: 'g',
  },
  {
    key: 'max_added_sugar_g',
    label: 'Plafond de sucres ajoutés',
    hint: 'Au-delà, la journée est signalée',
    unit: 'g',
  },
  {
    key: 'target_hydration_ml',
    label: 'Hydratation par jour',
    hint: 'Objectif de l’anneau et de la grille',
    unit: 'ml',
  },
];

/** Champs saisis, sous leur forme texte — un formulaire ne manipule que des chaînes. */
type Draft = Record<keyof SettingsValues, string>;

function toDraft(values: SettingsValues): Draft {
  return {
    target_weight_kg: String(values.target_weight_kg),
    target_protein_g: String(values.target_protein_g),
    max_added_sugar_g: String(values.max_added_sugar_g),
    target_hydration_ml: String(values.target_hydration_ml),
    hydration_presets_ml: values.hydration_presets_ml.join(', '),
    heatmap_metric: values.heatmap_metric,
  };
}

/**
 * Ce que le formulaire envoie : **seulement ce qui a changé**.
 *
 * L'API accepte une modification partielle, et lui envoyer les six clés à chaque
 * enregistrement écrirait des valeurs de repli dans le fichier — un objectif jamais
 * choisi deviendrait un objectif choisi, et il cesserait de suivre le défaut si celui-ci
 * évoluait.
 */
function changes(draft: Draft, current: SettingsValues): SettingsPayload {
  const before = toDraft(current);
  const payload: SettingsPayload = {};

  for (const spec of NUMBERS) {
    if (draft[spec.key] === before[spec.key]) continue;
    const parsed = Number.parseFloat(draft[spec.key].replace(',', '.'));
    if (Number.isFinite(parsed)) {
      // Le serveur porte les bornes de vraisemblance (`API-06`) : le client n'en
      // redéclare aucune, il transmet et affiche le refus.
      payload[spec.key] = parsed as never;
    }
  }

  if (draft.hydration_presets_ml !== before.hydration_presets_ml) {
    const volumes = draft.hydration_presets_ml
      .split(',')
      .map((chunk) => Number.parseInt(chunk.trim(), 10))
      .filter((value) => Number.isFinite(value));
    payload.hydration_presets_ml = volumes;
  }

  if (draft.heatmap_metric !== before.heatmap_metric) {
    payload.heatmap_metric = draft.heatmap_metric;
  }

  return payload;
}

function Origin({ view, field }: { view: SettingsView; field: keyof SettingsValues }) {
  const chosen = view.stored.includes(field);
  return <Badge tone={chosen ? 'signal' : 'load'}>{chosen ? 'réglé' : 'valeur par défaut'}</Badge>;
}

export function Settings() {
  const client = useQueryClient();
  const { notify } = useToast();

  const { data, isPending, error } = useQuery({
    queryKey: keys.settings.all(),
    queryFn: settingsApi.read,
  });

  const [draft, setDraft] = useState<Draft | null>(null);
  const [refusal, setRefusal] = useState<ApiError | null>(null);

  const save = useMutation({
    mutationFn: (view: SettingsView) =>
      settingsApi.update(changes(draft ?? toDraft(view.values), view.values), view.token),

    onSuccess: (updated) => {
      client.setQueryData(keys.settings.all(), updated);
      // Un objectif modifié change l'écart au poids cible, l'anneau de protéines et la
      // grille d'hydratation : les vues transverses doivent être rejouées, sinon le
      // tableau de bord mentirait jusqu'à la prochaine navigation.
      for (const key of CROSS_CUTTING) void client.invalidateQueries({ queryKey: key });
      void client.invalidateQueries({ queryKey: keys.hydration.all() });
      void client.invalidateQueries({ queryKey: keys.nutrition.all() });
      void client.invalidateQueries({ queryKey: keys.body.all() });

      setDraft(null);
      setRefusal(null);
      notify('Réglages enregistrés.', 'effort');
    },

    onError: (caught: unknown) => {
      setRefusal(caught instanceof ApiError ? caught : null);
      if (caught instanceof ApiError && caught.code === 'conflict') {
        // La garde a parlé : l'écran doit repartir de ce que le fichier vaut vraiment.
        void client.invalidateQueries({ queryKey: keys.settings.all() });
        setDraft(null);
      }
      notify(caught instanceof ApiError ? caught.message : 'Enregistrement impossible.', 'recover');
    },
  });

  if (isPending) {
    return (
      <div className="wrap">
        <p className={styles.empty}>chargement…</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="wrap">
        <Empty title="Réglages indisponibles">
          {error instanceof Error ? error.message : 'Le serveur n’a pas répondu.'}
        </Empty>
      </div>
    );
  }

  const fields = draft ?? toDraft(data.values);
  const set = (key: keyof SettingsValues) => (event: { target: { value: string } }) => {
    const value = event.target.value;
    setDraft((current) => ({ ...(current ?? toDraft(data.values)), [key]: value }));
  };

  const dirty = Object.keys(changes(fields, data.values)).length > 0;

  return (
    <div className="wrap">
      <p className="eyebrow">Réglages</p>
      <h1 style={{ marginTop: 10 }}>Objectifs &amp; repères</h1>
      <p className="lede" style={{ marginTop: 14 }}>
        Ces valeurs servent de référence à tous les écrans. Tant qu’un réglage n’est pas renseigné,
        c’est le défaut du serveur qui s’applique — et il est affiché tel quel, jamais deviné.
      </p>

      <Rule>Objectifs</Rule>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate(data);
        }}
        noValidate
      >
        {refusal !== null && refusal.fields.length === 0 && (
          <p className={styles.error} role="alert">
            {refusal.message}
          </p>
        )}

        <div className="grid g2">
          {NUMBERS.map((spec) => (
            <Card key={spec.key}>
              <div className="spread">
                <span className={styles.name}>{spec.label}</span>
                <Origin view={data} field={spec.key} />
              </div>
              <div className={styles.row}>
                <Field
                  label={spec.unit}
                  inputMode="decimal"
                  value={fields[spec.key]}
                  error={refusal?.messageFor(spec.key)}
                  hint={`${spec.hint} · défaut ${num(data.defaults[spec.key] as number, 1)} ${spec.unit}`}
                  onChange={set(spec.key)}
                />
              </div>
            </Card>
          ))}
        </div>

        <Rule>Saisie</Rule>

        <div className="grid g2">
          <Card>
            <div className="spread">
              <span className={styles.name}>Raccourcis d’hydratation</span>
              <Origin view={data} field="hydration_presets_ml" />
            </div>
            <Field
              label="Volumes, séparés par des virgules"
              value={fields.hydration_presets_ml}
              error={refusal?.messageFor('hydration_presets_ml')}
              hint={`Un à six boutons · défaut ${data.defaults.hydration_presets_ml.join(', ')} ml`}
              onChange={set('hydration_presets_ml')}
            />
          </Card>

          <Card>
            <div className="spread">
              <span className={styles.name}>Métrique mise en avant</span>
              <Origin view={data} field="heatmap_metric" />
            </div>
            <Field
              label="Clé de la piste"
              value={fields.heatmap_metric}
              error={refusal?.messageFor('heatmap_metric')}
              hint={`Les pistes d’assiduité arrivent au lot L11 · défaut ${data.defaults.heatmap_metric}`}
              onChange={set('heatmap_metric')}
            />
          </Card>
        </div>

        <div className={styles.actions}>
          <Button type="submit" variant="primary" busy={save.isPending} disabled={!dirty}>
            Enregistrer
          </Button>
          {dirty && (
            <Button
              variant="quiet"
              onClick={() => {
                setDraft(null);
                setRefusal(null);
              }}
            >
              Annuler
            </Button>
          )}
        </div>
      </form>

      <div style={{ height: 40 }} />
    </div>
  );
}
