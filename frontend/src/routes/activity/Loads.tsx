/**
 * Les charges des exercices de tabata — `/activite/charges`.
 *
 * Le plan est dans `docs/charges.md`. Ce que la page sert à faire tient en une phrase :
 * noter ce qu'on charge sur chaque exercice d'une séance Cadence, pour que le lien de
 * cette séance l'affiche sous le nom pendant l'effort.
 *
 * ## Ce qu'on y voit, et dans cet ordre
 *
 * **À renseigner** d'abord : c'est le seul endroit de la page où il reste un geste à
 * faire, et le mettre en bas reviendrait à le cacher. Puis les exercices **chargés**, avec
 * leur pas-à-pas. Puis ceux au **poids du corps**, en liste dense — rien à y régler, juste
 * à savoir qu'ils sont classés.
 *
 * C'est le serveur qui décide de l'état (`state`) et de l'ordre. L'écran groupe sur une
 * étiquette qu'il reçoit ; lui faire déduire « pas encore renseigné » d'un `null` serait
 * lui confier une règle qui vit là-bas, et il y a trois états à ne pas confondre.
 *
 * ## Un appui confirme
 *
 * Le pas-à-pas ajuste une valeur **locale** ; « Enregistrer » écrit. C'est ce qui fait
 * qu'un passage de 10 à 16 kg est *une* ligne de journal et *un* point sur la courbe, pas
 * six. Enregistrer sans avoir rien changé n'écrit rien du tout — le serveur le vérifie
 * aussi, mais l'écran n'a pas à envoyer une écriture qu'il sait vide.
 *
 * **Aucune suppression.** On corrige une valeur, on bascule au poids du corps ; on ne
 * revient pas à « jamais renseigné ». Le geste manque, il est nommé dans `charges.md` §10,
 * et il vaut mieux qu'un second vocabulaire de destruction sur une surface neuve.
 */

import { useMutation, useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import {
  Button,
  Card,
  Chart,
  DotRow,
  Empty,
  Field,
  LinkButton,
  PageHead,
  Sheet,
  Stepper,
} from '@/components/ui';
import { IconBodyweight, IconWeight } from '@/components/ui/icons';
import { activityApi, type Load, type LoadDetail, type LoadPayload } from '@/features/activity/api';
import { ApiError } from '@/lib/api';
import { cx } from '@/lib/cx';
import { dayMonth, num, plural } from '@/lib/format';
import { keys } from '@/lib/query';
import { useToast } from '@/lib/toast';

import styles from '../Activity.module.css';
import { fold, kgText, useInvalidateLoads } from './shared';

/** La charge d'une carte, telle qu'elle s'écrit. Un tiret quand rien n'est déclaré. */
function reading(load: Load): string {
  if (load.state === 'bodyweight') return 'poids du corps';
  if (load.weight_kg === null) return '—';
  return `${num(load.weight_kg, 1)} kg`;
}

/** Ce que la carte dit d'elle-même : pourquoi elle est là. */
function trace(load: Load): string {
  return `dans ${String(load.circuits)} ${plural(load.circuits, 'séance')}`;
}

/**
 * Depuis quand la charge n'a pas bougé, et ce qu'elle a tenu. `null` quand il n'y a rien
 * à dire.
 *
 * **Un constat, jamais un conseil** (**R10**). « changée il y a 24 jours · 3 séances
 * depuis » est une mesure ; « tu peux monter » serait une décision, et elle appartient à
 * l'utilisateur. Les deux chiffres arrivent calculés du serveur — l'écran n'en dérive
 * aucun, il les met en français.
 *
 * Rien n'est rendu quand le journal ne porte aucun changement : `null` n'est pas `0`, et
 * « changée il y a 0 jour » sur un exercice jamais chiffré serait faux. `0` séance, en
 * revanche, **est** une mesure et se dit — « montée hier, aucune séance depuis » est
 * précisément ce qu'on veut lire.
 *
 * **Sur sa propre ligne, et c'est le défaut qui l'a imposé.** Ajoutée à côté du nom, dans
 * un `.loadHead` en `flex` dont le nom porte `min-width: 0`, elle poussait le nom à une
 * largeur nulle et les deux textes se peignaient l'un sur l'autre. Vu en capture, pas par
 * un test : l'audit ne mesure ni les chevauchements de texte ni la longueur d'une phrase.
 */
function held(load: Load): string | null {
  if (load.days_since_change === null) return null;
  const quand =
    load.days_since_change === 0
      ? 'changée aujourd’hui'
      : `changée il y a ${String(load.days_since_change)} ${plural(load.days_since_change, 'jour')}`;
  if (load.sessions_since === null) return quand;
  const tenue =
    load.sessions_since === 0
      ? 'aucune séance depuis'
      : `${String(load.sessions_since)} ${plural(load.sessions_since, 'séance')} depuis`;
  return `${quand} · ${tenue}`;
}

export function Loads() {
  const invalidate = useInvalidateLoads();
  const { notify } = useToast();

  const {
    data,
    isPending,
    error: unreadable,
  } = useQuery({
    queryKey: keys.activity.loads(),
    queryFn: activityApi.loads,
  });

  /** L'exercice dont la feuille de détail est ouverte, par son nom. */
  const [opened, setOpened] = useState<string | null>(null);
  /** Les valeurs en cours d'ajustement, par nom. Elles n'existent que le temps du geste. */
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  /**
   * Les exercices au poids du corps qu'on est en train de rechiffrer.
   *
   * Une liste et non un seul nom : ouvrir le second ne doit pas effacer ce qu'on venait de
   * taper dans le premier. Rien n'est écrit tant qu'on n'a pas enregistré — c'est un état
   * d'écran, il disparaît au rechargement, et c'est très bien.
   */
  const [reweighing, setReweighing] = useState<string[]>([]);
  /**
   * Le filtre de la liste. **Local, et c'est légitime** : il range des cartes déjà
   * reçues, il ne décide pas que deux noms désignent le même exercice — ça, c'est
   * `app/core/text.py`, côté serveur. Le `Combobox` filtre de la même façon et porte la
   * même distinction dans sa doc.
   */
  const [query, setQuery] = useState('');
  const [error, setError] = useState<ApiError | null>(null);

  const save = useMutation({
    mutationFn: ({ load, weight }: { load: Load; weight: number | 'bodyweight' }) => {
      const payload: LoadPayload =
        weight === 'bodyweight'
          ? { name: load.name, bodyweight: true }
          : { name: load.name, weight_kg: weight };
      // Pas de ligne, pas de jeton : la première charge est une **addition**, la suivante
      // une modification sous garde (`STO-05`). C'est le serveur qui porte la règle ; ici
      // on lit simplement ce qu'il a renvoyé.
      return load.id === null || load.token === null
        ? activityApi.createLoad(payload)
        : activityApi.updateLoad(load.id, load.token, payload);
    },
    onSuccess: (saved) => {
      setError(null);
      // Le brouillon disparaît : ce que la carte affiche redevient ce que le serveur a
      // écrit. Le garder ferait diverger le champ de la valeur enregistrée au premier
      // arrondi.
      setDrafts((current) =>
        Object.fromEntries(Object.entries(current).filter(([name]) => name !== saved.name)),
      );
      setReweighing((current) => current.filter((name) => name !== saved.name));
      invalidate();
      notify(`${saved.name} · ${reading(saved)}`);
    },
    onError: (failure: unknown) => {
      if (failure instanceof ApiError) setError(failure);
    },
  });

  const loads = data?.loads ?? [];
  const step = data?.step_kg ?? 1;
  const needle = fold(query.trim());
  const shown = needle === '' ? loads : loads.filter((load) => fold(load.name).includes(needle));
  const unset = shown.filter((load) => load.state === 'unset');
  const weighted = shown.filter((load) => load.state === 'weighted');
  const bodyweight = shown.filter((load) => load.state === 'bodyweight');
  const reweighed = bodyweight.filter((load) => reweighing.includes(load.name));
  const resting = bodyweight.filter((load) => !reweighing.includes(load.name));

  function draftOf(load: Load): string {
    return drafts[load.name] ?? (load.weight_kg === null ? '' : kgText(load.weight_kg));
  }

  function card(load: Load) {
    const draft = draftOf(load);
    const typed = Number(draft.replace(',', '.'));
    const usable = draft.trim() !== '' && Number.isFinite(typed) && typed > 0;
    const changed = load.weight_kg === null || Math.abs(typed - load.weight_kg) > 1e-9;
    const busy = save.isPending && save.variables?.load.name === load.name;

    return (
      <Card key={load.name} className={styles.loadCard}>
        {/* Deux lignes, et pas deux colonnes. Une colonne de nom à côté d'une colonne de
            commande cassait « Développé haltères assis » sur deux lignes tout en laissant
            la commande sur une seule : des cartes de hauteurs inégales dans une grille,
            exactement le défaut que `LogButton` traîne déjà. En pleine largeur, le nom a
            la place de tenir, et le pas-à-pas celle de garder son champ au-dessus de
            44 px. */}
        <div className={styles.loadHead}>
          <button
            type="button"
            className={styles.loadName}
            onClick={() => {
              setOpened(load.name);
            }}
          >
            {load.name}
          </button>
          <span className={styles.note}>{trace(load)}</span>
        </div>

        {/* Le constat du coach, sous l'en-tête et non dedans — voir `held`. Absent tant
            que le journal ne porte aucun changement : la carte ne grandit que quand elle a
            quelque chose à dire. */}
        {held(load) !== null && <span className={styles.note}>{held(load)}</span>}

        <div className={styles.loadControl}>
          <Stepper
            label="Charge"
            labelHidden
            unit="kg"
            value={draft}
            step={step}
            min={0}
            placeholder="—"
            onChange={(value) => {
              setDrafts((current) => ({ ...current, [load.name]: value }));
            }}
          />

          {/* Une icône et non un bouton en toutes lettres : « Au poids du corps » sur sa
              propre ligne coûtait 44 px de haut à **chaque** carte, pour un geste qu'on
              fait une fois par exercice et jamais plus. Le libellé part dans `aria-label`
              et `title` — il n'a pas disparu, il a quitté la hauteur. */}
          {load.state !== 'bodyweight' && (
            <button
              type="button"
              className={styles.loadIcon}
              aria-label={`${load.name} : au poids du corps`}
              title="Au poids du corps"
              disabled={busy}
              onClick={() => {
                save.mutate({ load, weight: 'bodyweight' });
              }}
            >
              <IconBodyweight />
            </button>
          )}
        </div>

        {/* Le bouton n'existe **que** quand il y a quelque chose à enregistrer. Un bouton
            désactivé en permanence occupe la place et n'apprend rien ; celui-ci apparaît
            au premier appui sur `+` et dit qu'un geste reste à faire. */}
        {usable && changed && (
          <Button
            variant="primary"
            disabled={busy}
            onClick={() => {
              save.mutate({ load, weight: typed });
            }}
          >
            Enregistrer
          </Button>
        )}
      </Card>
    );
  }

  return (
    <div className={cx('wrap', styles.screen)}>
      <PageHead
        eyebrow="Activité"
        title="Charges"
        actions={
          <LinkButton variant="quiet" to="/activite">
            Retour à l’activité
          </LinkButton>
        }
      >
        Ce que tu notes ici s’affiche sous le nom de l’exercice pendant la séance, dans Cadence.
      </PageHead>

      {/* La recherche vit **au-dessus** des trois sections et les filtre toutes : chercher
          « rowing » sans savoir s'il est chargé ou au poids du corps est exactement la
          raison d'avoir un champ. Elle ne s'affiche pas tant qu'il n'y a rien à filtrer —
          un champ de recherche sur une liste vide est un contrôle qui ne mène nulle part. */}
      {loads.length > 0 && (
        <Field
          label="Rechercher un exercice"
          type="search"
          placeholder="rowing, gainage…"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
          }}
        />
      )}

      {error !== null && (
        <p className={styles.error} role="alert">
          {error.message}
        </p>
      )}

      {isPending && <p className={styles.note}>Chargement…</p>}

      {unreadable !== null && !isPending && (
        <Empty title="Charges indisponibles">
          {unreadable instanceof ApiError
            ? unreadable.message
            : 'Le stockage n’a pas répondu. Réessaie dans un instant.'}
        </Empty>
      )}

      {/* L'état vide n'est pas « aucune charge » mais « aucune séance » : sans circuit, il
          n'y a aucun exercice à charger, et le geste qui coûte le moins est de créer la
          séance — pas de chercher une charge à noter. */}
      {!isPending && unreadable === null && loads.length === 0 && (
        <Empty
          title="Aucune séance tabata"
          action={<LinkButton to="/activite/seances">Créer une séance</LinkButton>}
        >
          Les charges se notent sur les exercices d’une séance Cadence. Crées-en une, ses exercices
          apparaîtront ici.
        </Empty>
      )}

      {!isPending && unreadable === null && loads.length > 0 && shown.length === 0 && (
        <Empty title="Aucun exercice ne correspond">
          Aucun exercice de tabata ne porte « {query.trim()} ». Efface la recherche pour revoir les{' '}
          {String(loads.length)} de tes séances.
        </Empty>
      )}

      {unset.length > 0 && (
        <section className={styles.section}>
          <h2 className="eyebrow">À renseigner</h2>
          <div className={styles.cards}>{unset.map(card)}</div>
        </section>
      )}

      {weighted.length > 0 && (
        <section className={styles.section}>
          <h2 className="eyebrow">Chargés</h2>
          <div className={styles.cards}>{weighted.map(card)}</div>
        </section>
      )}

      {bodyweight.length > 0 && (
        <section className={styles.section}>
          <h2 className="eyebrow">Poids du corps</h2>
          {/* Ceux qu'on rechiffre quittent la liste dense et prennent une carte, celle des
              autres : on ne réinvente pas un second contrôle de charge pour le même geste.
              Ils restent sous ce titre tant que rien n'est enregistré — c'est encore leur
              état, et les faire sauter de section avant l'écriture mentirait sur ce que le
              fichier porte. */}
          {reweighed.length > 0 && <div className={styles.cards}>{reweighed.map(card)}</div>}

          {resting.length > 0 && (
            <Card>
              {resting.map((load) => (
                <div className={styles.loadDense} key={load.name}>
                  <button
                    type="button"
                    className={styles.loadDenseName}
                    onClick={() => {
                      setOpened(load.name);
                    }}
                  >
                    <span>{load.name}</span>
                    <span className={styles.note}>{trace(load)}</span>
                  </button>
                  {/* Discret, et à droite comme tous les réglages de charge de la page.
                        Il n'écrit rien : il rend le pas-à-pas, et c'est l'enregistrement
                        qui bascule la ligne. Sans cette étape, l'appui poserait une charge
                        que personne n'a choisie. */}
                  {/* Il n'écrit rien : il rend le pas-à-pas, et c'est l'enregistrement qui
                      bascule la ligne. Sans cette étape, l'appui poserait une charge que
                      personne n'a choisie — et rien ne se défait dans ce projet. */}
                  <button
                    type="button"
                    className={styles.loadIcon}
                    aria-label={`${load.name} : remettre une charge`}
                    title="Remettre une charge"
                    onClick={() => {
                      setReweighing((current) => [...current, load.name]);
                    }}
                  >
                    <IconWeight />
                  </button>
                </div>
              ))}
            </Card>
          )}
        </section>
      )}

      <LoadSheet
        name={opened}
        onClose={() => {
          setOpened(null);
        }}
      />
    </div>
  );
}

/**
 * Le détail d'un exercice : la courbe des décisions, puis les trente derniers jours.
 *
 * Les deux séries viennent de **deux fichiers différents** et peuvent diverger — une
 * charge notée et jamais soulevée monte la courbe sans allumer un point. C'est exactement
 * ce qu'on veut voir, et c'est pour ça qu'elles sont l'une au-dessus de l'autre.
 */
function LoadSheet({ name, onClose }: { name: string | null; onClose: () => void }) {
  const { data, isPending } = useQuery({
    queryKey: keys.activity.load(name ?? ''),
    queryFn: () => activityApi.loadDetail(name ?? ''),
    enabled: name !== null,
  });

  return (
    <Sheet open={name !== null} onClose={onClose} title={name ?? ''}>
      {isPending && <p className={styles.note}>Chargement…</p>}
      {data !== undefined && <LoadDetailBody detail={data} />}
    </Sheet>
  );
}

/**
 * La démonstration de l'exercice, quand l'instance de l'utilisateur en sert une.
 *
 * **Rien à la place quand il n'y en a pas.** Le serveur rend `null` pour trois raisons —
 * pas d'adresse réglée, instance injoignable, nom sans correspondance — et aucune
 * n'appelle un geste : un encart « démonstration indisponible » ferait passer pour une
 * panne l'état normal d'un exercice écrit à la main.
 *
 * `onError` couvre le quatrième cas, celui que le serveur ne peut pas voir : l'adresse
 * était bonne à la réponse et l'instance s'est éteinte entre-temps. Le cadre vide qui
 * resterait sinon est le seul de tous ces cas qui ressemble à un bug.
 */
function Demo({ url, name }: { url: string; name: string }) {
  const [broken, setBroken] = useState(false);
  if (broken) return null;

  return (
    <img
      className={styles.demo}
      src={url}
      alt={`Démonstration de ${name}`}
      // Le navigateur va la chercher sur une autre origine : sans cela, il y enverrait
      // l'adresse de Metric en `Referer`.
      referrerPolicy="no-referrer"
      loading="lazy"
      onError={() => {
        setBroken(true);
      }}
    />
  );
}

function LoadDetailBody({ detail }: { detail: LoadDetail }) {
  /**
   * Les points de la courbe, sans ceux qui n'en sont pas.
   *
   * Un passage au poids du corps porte `weight_kg` à `null` : il **interrompt** la charge
   * plutôt que de la ramener à zéro, et zéro sur un axe de kilos serait une charge nulle.
   * Ces points sortent donc de la courbe ; la carte, elle, dit l'état courant.
   */
  const points = detail.history.filter((point) => point.weight_kg !== null);
  const sessions = detail.sessions.reduce((total, entry) => total + entry.count, 0);

  return (
    <>
      {/* En tête : elle dit **de quel mouvement on parle**, ce qu'un nom anglais du
          catalogue ne dit pas toujours. Sous la charge, elle aurait été un ornement en bas
          de feuille ; au-dessus, elle identifie ce qu'on est en train de lire. */}
      {detail.demo_url ? <Demo url={detail.demo_url} name={detail.name} /> : null}

      {/* Le chiffre qu'on vient chercher, écrit. Il se lisait sur l'axe de la courbe, ce
          qui demande de savoir lequel des cinq points est le dernier — et ne se lit pas du
          tout quand il n'y a pas de courbe. */}
      <p className={styles.reading}>
        {detail.state === 'bodyweight'
          ? 'Au poids du corps'
          : detail.weight_kg === null
            ? 'Aucune charge notée'
            : `${num(detail.weight_kg, 1)} kg`}
      </p>
      {/* Moins de deux points n'est pas une évolution. Tracer une ligne d'un seul point
          laisserait croire à une tendance ; on affiche la valeur et sa date. */}
      {points.length >= 2 ? (
        <Chart
          labels={points.map((point) => dayMonth(point.date))}
          primary={{
            label: 'Charge',
            values: points.map((point) => point.weight_kg ?? 0),
            tone: 'load',
            unit: 'kg',
            format: (value) => `${num(value, 1)} kg`,
          }}
        />
      ) : (
        <p className={styles.note}>
          {points.length === 1 && points[0] !== undefined
            ? `Une seule charge notée, le ${dayMonth(points[0].date)}. La courbe demande un second point.`
            : 'Aucune charge notée pour l’instant.'}
        </p>
      )}

      <h3 className="eyebrow">30 derniers jours</h3>
      <DotRow
        label={`${String(sessions)} ${plural(sessions, 'séance')} sur les 30 derniers jours`}
        dots={detail.sessions.map((entry) => ({
          label: `${dayMonth(entry.date)} · ${String(entry.count)} ${plural(entry.count, 'séance')}`,
          // Le niveau vient d'un compte, pas d'une comparaison faite ici : deux séances
          // dans la journée sont rares, et au-delà l'échelle sature plutôt que de se
          // recalculer sur le maximum du mois — un mois calme changerait sinon la couleur
          // d'un jour identique.
          level: Math.min(entry.count / 2, 1),
        }))}
      />
      <p className={styles.note}>
        {sessions === 0
          ? 'Aucune séance avec cet exercice sur la période.'
          : `${String(sessions)} ${plural(sessions, 'séance')} · ${detail.circuits.join(' · ')}`}
      </p>
    </>
  );
}
