import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { Badge, Button, Card, Empty, Field, PageHead, Rule, Segmented } from '@/components/ui';
import {
  settingsApi,
  type SettingsPayload,
  type SettingsValues,
  type SettingsView,
} from '@/features/settings/api';
import { useAiStatus } from '@/features/ai/useAiStatus';
import { ApiError } from '@/lib/api';
import { cx } from '@/lib/cx';
import { num } from '@/lib/format';
import { CROSS_CUTTING, keys } from '@/lib/query';
import { useTheme, type ThemeMode } from '@/lib/theme';
import { useToast } from '@/lib/toast';

import { Profile } from './settings/Profile';
import { Reminders } from './settings/Reminders';
import { Tracks } from './settings/Tracks';

import styles from './Settings.module.css';

/**
 * Les réglages généralistes (`L08-08`) et les pistes d'assiduité (`L11-10`).
 *
 * Les deux vivent sur le même écran parce qu'ils répondent à la même question — « qu'est-ce
 * que je vise ? » — et parce que la piste mise en avant *est* le réglage `heatmap_metric`.
 * Les séparer aurait obligé à expliquer deux fois où se règle la même chose.
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
    cadence_base_url: values.cadence_base_url,
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

  /*
   * **Le seul champ dont la chaîne vide part au serveur.** Partout ailleurs, un champ
   * vidé serait une saisie en cours et le laisser filer écraserait un objectif par rien.
   * Ici, vide *est* la valeur — « pas d'adresse » — et c'est la seule façon d'effacer un
   * réglage qui n'a aucun défaut sur lequel retomber.
   */
  if (draft.cadence_base_url.trim() !== before.cadence_base_url) {
    payload.cadence_base_url = draft.cadence_base_url.trim();
  }

  return payload;
}

const THEMES: readonly { value: ThemeMode; label: string }[] = [
  { value: 'system', label: 'Système' },
  { value: 'light', label: 'Clair' },
  { value: 'dark', label: 'Sombre' },
];

/**
 * Le thème de l'interface.
 *
 * **C'est le seul réglage de cet écran qui ne va pas au serveur**, et la carte le dit :
 * un thème est une préférence d'appareil, pas une donnée du journal. Le téléphone peut
 * vouloir le sombre quand l'ordinateur veut le clair, et rien dans le fichier de réglages
 * ne saurait arbitrer.
 *
 * La section est rendue dans les trois états de l'écran — chargement, erreur, données.
 * Elle ne dépend d'aucune requête, et un utilisateur qui trouve l'interface illisible
 * doit pouvoir la corriger même quand l'API ne répond pas.
 */
function Appearance() {
  const { mode, theme, setMode } = useTheme();

  return (
    <>
      <Rule>Apparence</Rule>
      <Card>
        <div className="spread">
          <span className={styles.name}>Thème</span>
          {/* Même vocabulaire que les objectifs plus haut : ce qui est choisi porte
              « réglé », ce qui suit un défaut dit lequel il suit. */}
          <Badge tone={mode === 'system' ? 'load' : 'signal'}>
            {mode === 'system' ? `système · ${theme === 'light' ? 'clair' : 'sombre'}` : 'réglé'}
          </Badge>
        </div>
        <p className={cx(styles.note, styles.noteSpaced)}>
          « Système » suit la préférence de l’appareil et change avec elle. Un choix explicite
          l’emporte, et il reste sur ce navigateur — il n’est pas enregistré au serveur.
        </p>
        <div className={styles.row}>
          <Segmented
            label="Thème de l’interface"
            options={THEMES}
            value={mode}
            onChange={setMode}
          />
        </div>
      </Card>
    </>
  );
}

/**
 * Le pont vers Cadence Tabata (**D1**) — une adresse, et rien d'autre.
 *
 * ── Pourquoi ce réglage ne porte pas le badge « valeur par défaut » ────────
 *
 * `Origin` lit `stored`, c'est-à-dire « la clé est-elle dans le fichier ». Ça marche pour
 * un objectif, où la clé absente veut dire « je suis le défaut ». Ça ment ici : effacer
 * l'adresse **écrit** une cellule vide, donc la clé y est, donc `stored` dirait « réglé »
 * d'un champ vide. Le badge lit donc la valeur, qui est la question qu'on se pose vraiment
 * — y a-t-il une adresse, oui ou non.
 *
 * ── Ce que dit la carte quand elle est vide ───────────────────────────────
 *
 * Le prochain geste, et son coût : ouvrir Cadence, copier l'adresse de la barre. Pas un
 * exemple de domaine — un domaine plausible affiché en gris finit par être recopié tel
 * quel, et ce serait une valeur inventée.
 */
function CadenceCard({
  value,
  error,
  onChange,
}: {
  value: string;
  error: string | undefined;
  onChange: (event: { target: { value: string } }) => void;
}) {
  const set = value.trim() !== '';

  return (
    <>
      <Rule>Applications</Rule>
      <Card>
        <div className="spread">
          <span className={styles.name}>Cadence Tabata</span>
          <Badge tone={set ? 'signal' : 'load'}>{set ? 'renseignée' : 'non renseignée'}</Badge>
        </div>
        <p className={cx(styles.note, styles.noteSpaced)}>
          {set
            ? 'Les séances s’ouvrent dans cette application. Rien n’y est envoyé : le lien contient la séance entière.'
            : 'Sans adresse, les séances se créent et se modifient, mais aucune ne s’ouvre. Ouvre Cadence et recopie l’adresse de la barre du navigateur.'}
        </p>
        {/* `.row` et non un style en ligne : `noteSpaced` n'espace que par le haut, et
            sans lui le paragraphe colle à l'étiquette du champ — vu en capture. C'est le
            même enveloppement que les cartes d'objectifs, pas une seconde façon d'espacer. */}
        <div className={styles.row}>
          <Field
            label="Adresse de l’application"
            type="url"
            inputMode="url"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            value={value}
            error={error}
            hint="Une clé dans l’adresse est acceptée, une ancre « # » non · vide pour effacer"
            onChange={onChange}
          />
        </div>
      </Card>
    </>
  );
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
      // Les rappels vivent dans le **même fichier** (`NOT-03`) : cette écriture change le
      // jeton que la section « Rappels » détient. Sans cette ligne, son prochain
      // enregistrement partirait en `409` sans que rien ne l'explique — les deux sections
      // se marcheraient dessus sur un écran où l'on descend naturellement de l'une à
      // l'autre.
      void client.invalidateQueries({ queryKey: keys.notifications.all() });

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
        {/* L'en-tête est là **avant** la donnée. Un écran qui n'affiche qu'un
          « chargement… » sur fond noir ne dit pas où l'on vient d'arriver, et la seconde
          d'attente se lit comme un écran qui n'a pas répondu. */}
        <PageHead eyebrow="Réglages" title={<>Objectifs &amp; repères</>} />
        <p className={styles.empty}>chargement…</p>
        <Appearance />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="wrap">
        <PageHead eyebrow="Réglages" title={<>Objectifs &amp; repères</>} />
        <Empty title="Réglages indisponibles">
          {error instanceof Error ? error.message : 'Le serveur n’a pas répondu.'}
        </Empty>
        <Appearance />
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
      <PageHead eyebrow="Réglages" title={<>Objectifs &amp; repères</>}>
        Ces valeurs servent de référence à tous les écrans. Tant qu’un réglage n’est pas renseigné,
        c’est le défaut du serveur qui s’applique — et il est affiché tel quel, jamais deviné.
      </PageHead>

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
              hint={`Se règle aussi d’un clic depuis les pistes, plus bas · défaut ${data.defaults.heatmap_metric}`}
              onChange={set('heatmap_metric')}
            />
          </Card>
        </div>

        <CadenceCard
          value={fields.cadence_base_url}
          error={refusal?.messageFor('cadence_base_url')}
          onChange={set('cadence_base_url')}
        />

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

      <Tracks />

      <Profile />

      <Reminders />

      <Appearance />

      <AiSection />
    </div>
  );
}

/**
 * L'état de l'assistance IA (`IA-07`).
 *
 * Il se dit **ici** et pas sur les écrans qui s'en servent : une carte d'import
 * définitivement inerte sur l'écran Activité serait du bruit à chaque visite, alors que
 * l'absence de clé est un fait de configuration — et les réglages sont l'endroit où l'on
 * vient chercher pourquoi quelque chose ne s'affiche pas.
 *
 * Le message vient du serveur : lui seul sait s'il a une clé, et il le dit en français.
 */
function AiSection() {
  const ai = useAiStatus();

  return (
    <>
      <Rule>Assistance</Rule>
      <Card>
        <div className="spread">
          <h3>Estimations et import</h3>
          <Badge tone={ai.enabled ? 'effort' : 'recover'}>
            {ai.enabled ? 'disponible' : 'hors service'}
          </Badge>
        </div>
        <p className={cx(styles.note, styles.noteSpaced)}>
          {ai.message ||
            'État inconnu : le serveur n’a pas répondu. Tout se saisit à la main, sans rien perdre.'}
        </p>
        <p className={cx(styles.note, styles.noteSpaced)}>
          Ce qu’une estimation propose n’est jamais enregistré sans validation, et se corrige au
          doigt avant de l’être.
        </p>
      </Card>
    </>
  );
}
