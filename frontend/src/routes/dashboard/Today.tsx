/**
 * La journée : ce qu'il reste à faire, et les trois chiffres qui la situent.
 *
 * ## « Il reste aujourd'hui » n'est pas une routine bis
 *
 * La liste **dit un écart, elle n'écrit rien**. Le `⊕` de la barre d'onglets sait déjà
 * noter un verre, un supplément et une pesée sans changer d'écran, et `/routine` détient
 * la case à cocher. Rendre ces lignes cochables aurait donné un second vocabulaire pour le
 * même geste — exactement ce que `CLAUDE.md` §6 dit d'éviter — et deux chemins d'écriture
 * à tenir en phase sur la surface la plus visitée.
 *
 * Ce qu'elle remplace : la carte « Journée », qui portait les mêmes trois jauges enterrées
 * sous la tendance, à un écran et demi de défilement du haut de page.
 *
 * ## Les trois chiffres, et pourquoi ils ne sont plus quatre
 *
 * L'hydratation a quitté la bande. Elle y disait le **total** quand la liste dit le
 * **restant** : deux lectures de la même mesure à deux endroits d'un même écran, c'est une
 * de trop, et c'est celle qui se lit le moins bien qui part.
 *
 * Ils n'ont plus de carte non plus. Trois chiffres nus, en chasse fixe, sur une seule
 * rangée : c'est ce qui les rend lisibles d'un coup d'œil, là où quatre cartes de poids
 * égal demandaient de choisir laquelle regarder — le reproche exact d'où part ce lot.
 */

import { Link } from 'react-router';

import { Badge, Card, Empty, LinkButton, Progress, Rule, Stat } from '@/components/ui';
import type { DashboardView, DayTask } from '@/features/aggregates/api';
import type { PlannedSession } from '@/features/planning/api';
import { cx } from '@/lib/cx';
import { delta, hoursMinutes, integer, num, plural, volume } from '@/lib/format';

import styles from '../Dashboard.module.css';

/**
 * Où mène chaque ligne.
 *
 * **Une table de correspondance, pas un calcul** — c'est ce que dit déjà le commentaire de
 * `DayTask.key` côté serveur. Le serveur nomme la ligne, l'écran sait où elle se remplit :
 * l'inverse aurait mis des adresses d'interface dans un schéma d'API, qui n'en a que faire
 * et qui les verrait mentir au premier renommage de route.
 *
 * L'eau et les suppléments mènent au même écran, et ce n'est pas un raccourci : `/routine`
 * s'intitule « Hydratation & suppléments » et porte les deux.
 */
const DESTINATIONS: Record<string, { to: string; where: string }> = {
  hydration: { to: '/routine', where: 'Hydratation & suppléments' },
  protein: { to: '/nutrition', where: 'Nutrition' },
  supplements: { to: '/routine', where: 'Hydratation & suppléments' },
};

/**
 * Le chiffre d'une ligne, dans son unité.
 *
 * **`null` n'est pas `0`.** Rien de noté rend un tiret : un zéro à côté d'une cible se
 * lirait comme une mesure, et c'est la faute que le §2 nomme en premier. Le serveur
 * distingue déjà les deux ; ce composant se contente de ne pas les recoller.
 */
function amount(value: number | null, unit: string): string {
  if (value === null) return '—';
  if (unit === 'ml') return volume(value);
  if (unit === 'prises') return integer(value);
  return `${num(value, 0)} ${unit}`;
}

function target(value: number, unit: string): string {
  if (unit === 'ml') return volume(value);
  if (unit === 'prises') return `${integer(value)} ${plural(value, 'prise')}`;
  return `${num(value, 0)} ${unit}`;
}

/**
 * Le chevron d'ouverture.
 *
 * **Il appartient à la ligne, pas aux chiffres.** Posé au bout de la rangée de valeurs, il
 * se lisait comme leur suite — « 2,5 L › » formait un seul bloc, vu en capture. Il vit
 * donc à droite de la ligne entière, centré sur sa hauteur, comme sur toute liste qui
 * s'ouvre.
 *
 * `aria-hidden` : la destination est déjà dans l'`aria-label` du lien, en toutes lettres.
 * Un lecteur d'écran annonce « Ouvrir Nutrition », pas un chevron.
 */
function Chevron() {
  return (
    <span className={styles.taskGo} aria-hidden="true">
      ›
    </span>
  );
}

/**
 * Une ligne, et la porte qui va avec.
 *
 * **La ligne entière est le lien**, pas un chevron isolé à viser au pouce : elle fait plus
 * de 44 px de haut à elle seule, et elle est pleine largeur de carte. C'est le contraire
 * du défaut que la mesure du DOM avait trouvé au L13 — un lien de 17 px dans une phrase.
 *
 * **Elle ne coche toujours rien.** Naviguer n'est pas écrire : la case à cocher reste dans
 * `/routine` et le `⊕` de la barre garde la saisie en un chiffre. Il n'y a donc toujours
 * qu'un vocabulaire pour noter un verre — cette ligne y **mène**, elle ne le double pas.
 * C'est aussi ce que dit la pastille, qui est ronde et pleine plutôt que carrée et cochée.
 */
function Task({ task }: { task: DayTask }) {
  const destination = DESTINATIONS[task.key];
  const body = (
    <>
      <div className={styles.taskHead}>
        {/* Une pastille d'**état**, pas une case à cocher : elle ne se touche pas, et
            `aria-hidden` la retire du parcours — la phrase du restant dit déjà « fait ». */}
        <span className={cx(styles.mark, task.complete && styles.markDone)} aria-hidden="true" />
        <span className={styles.taskLabel}>{task.label}</span>
        <span className={styles.taskCount}>
          {amount(task.done, task.unit)}
          <span className={styles.taskTarget}> / {target(task.target, task.unit)}</span>
        </span>
      </div>

      <Progress bare done={Math.round(task.done ?? 0)} total={Math.round(task.target)} />

      {/* La phrase vient du serveur, en français, et s'affiche telle quelle : la
          soustraction est faite une fois, par le domaine qui détient la cible. */}
      <span className={cx(styles.taskLeft, task.complete && styles.taskDone)}>
        {task.remaining}
      </span>
    </>
  );

  // Une clé que l'écran ne connaît pas reste **lisible**, sans porte. Le serveur peut
  // ajouter une ligne avant que le client sache où elle mène ; l'afficher morte vaut mieux
  // que de la faire disparaître ou de l'envoyer au hasard.
  if (destination === undefined) {
    return (
      <li className={styles.task}>
        <div className={styles.taskBody}>{body}</div>
      </li>
    );
  }

  return (
    <li>
      <Link
        to={destination.to}
        className={cx(styles.task, styles.taskLink)}
        aria-label={`${task.label} : ${task.remaining}. Ouvrir ${destination.where}.`}
      >
        <div className={styles.taskBody}>{body}</div>
        <Chevron />
      </Link>
    </li>
  );
}

/**
 * La séance prévue, en dernière ligne.
 *
 * **Elle n'est jamais dite « faite ».** Le rapprochement prévu / réalisé est la règle de
 * `PLAN-06`, et en écrire une seconde version ici donnerait deux verdicts pour le même
 * mardi. Sa pastille est donc creuse en permanence, et son état se lit « prévu ».
 */
function Session({ session, today }: { session: PlannedSession; today: string }) {
  const when =
    session.date === today
      ? 'aujourd’hui'
      : `le ${session.date.slice(8)}/${session.date.slice(5, 7)}`;

  return (
    <li>
      <Link
        to="/planning"
        className={cx(styles.task, styles.taskLink)}
        aria-label={`${session.title}, prévu ${when}. Ouvrir le planning.`}
      >
        <div className={styles.taskBody}>
          <div className={styles.taskHead}>
            <span className={cx(styles.mark, styles.markPlanned)} aria-hidden="true" />
            <span className={styles.taskLabel}>{session.title}</span>
            <span className={styles.taskCount}>{session.time ?? '—'}</span>
          </div>
          <span className={styles.taskLeft}>
            prévu {when} · {hoursMinutes(session.duration_min)}
          </span>
        </div>
        <Chevron />
      </Link>
    </li>
  );
}

export function Today({ data }: { data: DashboardView }) {
  const { day, next_session: session, weight, training, streak } = data;

  return (
    <>
      <Rule>Il reste aujourd’hui</Rule>

      {/* L'état vide de l'écran, et il **porte** le geste au lieu de le décrire.
          « Une pesée » et « un verre d'eau » furent des liens en ligne dans une phrase :
          19 px de haut, mesurés — deux cibles sous le plancher tactile sur l'écran qu'on
          ouvre le plus.

          Il se déclenche sur `day.logged`, servi par le serveur : l'écran le recollait à
          partir de quatre champs et annonçait « aucun relevé » un jour où l'on avait
          couru. */}
      {!day.logged && (
        <div className={styles.dayEmpty}>
          <Empty
            title="Aucun relevé aujourd’hui"
            action={
              <div className="row">
                <LinkButton to="/corps">Noter une pesée</LinkButton>
                <LinkButton to="/routine">Boire un verre</LinkButton>
              </div>
            }
          >
            Deux chiffres suffisent pour que la journée compte.
          </Empty>
        </div>
      )}

      <Card>
        <div className="spread">
          <h3>La journée</h3>
          <Badge tone={day.done === day.total ? 'effort' : 'signal'} mono>
            {integer(day.done)} / {integer(day.total)}
          </Badge>
        </div>

        <ul className={styles.tasks}>
          {day.tasks.map((task) => (
            <Task key={task.key} task={task} />
          ))}
          {session !== null && <Session session={session} today={data.date} />}
        </ul>

        {/* Rien de prévu n'est pas un manquement : c'est une information, et elle dit où
            aller pour que ça change. Aucun chiffre inventé, aucun zéro. */}
        {session === null && (
          <p className={styles.taskNone}>
            Aucune séance prévue d’ici deux semaines. Le planning en pose une en trois appuis.
          </p>
        )}

        {/* Le plafond de sucres. Il vivait dans la carte « Journée », qui a fusionné avec
            cette liste ; il la suit plutôt que de disparaître avec elle. Ce n'est **pas**
            une ligne de la liste : un plafond dépassé ne se rattrape pas dans la journée,
            et le ranger parmi ce qu'il reste à faire aurait promis le contraire. */}
        {data.nutrition.over_sugar && (
          <p className={styles.warn}>
            Plafond de sucres dépassé : {num(data.nutrition.added_sugar_g, 1)} g sur{' '}
            {num(data.nutrition.added_sugar_max_g, 0)} g.
          </p>
        )}
      </Card>

      {/* La bande de chiffres. Pas de carte : trois nombres et leurs libellés, sur une
          rangée qui tient à 390 px. */}
      <div className={styles.strip}>
        <div className={styles.stripCell}>
          <Stat
            compact
            label="Poids"
            value={weight.latest_kg !== null ? num(weight.latest_kg, 1) : '—'}
            unit={weight.latest_kg !== null ? 'kg' : undefined}
            detail={
              weight.change_kg !== null
                ? `${delta(weight.change_kg)} kg sur 8 pesées`
                : weight.latest_kg !== null
                  ? // Il y a un chiffre : lui dire d'en poser un se lisait comme un écran
                    // qui n'a pas vu la pesée qu'il affiche juste au-dessus.
                    'la tendance vient à la deuxième'
                  : 'un chiffre le matin, et la courbe commence'
            }
            direction={weight.change_kg === null ? undefined : weight.change_kg > 0 ? 'up' : 'down'}
          />
        </div>

        <div className={styles.stripCell}>
          <Stat
            compact
            // « Cette semaine » passait sur deux lignes quand « Poids » et « Assiduité »
            // tenaient sur une : les trois chiffres ne partageaient plus de ligne de base,
            // et une rangée de nombres décalés se compare mal. Vu en capture.
            label="Semaine"
            value={training.week.sessions > 0 ? hoursMinutes(training.week.minutes) : '—'}
            detail={
              training.week.sessions > 0
                ? `${integer(training.week.sessions)} ${plural(training.week.sessions, 'séance')} · ${num(training.week.distance_km, 1)} km`
                : 'rien depuis lundi'
            }
          />
        </div>

        <div className={styles.stripCell}>
          <Stat
            compact
            label="Assiduité"
            value={streak.current > 0 ? integer(streak.current) : '—'}
            unit={streak.current > 0 ? plural(streak.current, 'jour') : undefined}
            detail={
              streak.longest > 0
                ? `record ${integer(streak.longest)} · ${integer(streak.active_days)} jours suivis`
                : 'une donnée, et la série démarre'
            }
          />
        </div>
      </div>
    </>
  );
}
