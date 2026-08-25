"""Le lien de séance de Cadence Tabata — construire, relire, estimer (**D7**).

Module **pur**, comme `progress.py` et `splits.py` : aucun fichier, aucun modèle, ni
pydantic ni FastAPI. Ce qui décide se teste sur des valeurs fixes.

## Pourquoi ce fichier ne s'appelle pas `cadence.py`

`app/core/cadence.py` décrit déjà la **fréquence** d'une piste d'assiduité, et
`RunRow.cadence_spm` compte des pas par minute. Trois sens pour un mot dans un même dépôt,
c'est deux de trop. Le module dit donc ce qu'il fait ; le nom de l'application tierce reste
là où il désigne vraiment quelque chose — le réglage `cadence_base_url` et l'interface.

## Pourquoi le serveur construit le lien, et pas l'écran

L'échappement `~ → %7E`, le bornage à 99 rounds, le suffixe `x` qui distingue quinze
répétitions de quinze secondes : ce sont des règles, pas du formatage. Le client reçoit une
adresse déjà faite et la pose dans un `href`.

Et pas le modèle non plus. `Pompes:15:20` au lieu de `Pompes:15x:20` est la faute que la
spécification appelle « la plus fréquente », et elle est **silencieuse** : la séance se
lance, elle est simplement fausse — quinze secondes au lieu de quinze répétitions.

## Le bornage est ici, alors que les schémas bornent déjà

Ce n'est pas une double validation par prudence. Cadence **ramène** les valeurs hors bornes
dans l'intervalle au lieu de les rejeter : une séance à 500 rounds s'y exécute à 99. Si le
bornage n'existait que dans le schéma, une ligne corrigée à la main dans le tableur ferait
diverger ce que Metric estime de ce que Cadence exécute. `normalise` est donc appliquée par
`build_url` **et** par `estimate`, sur les mêmes valeurs, pour que les deux racontent la
même séance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote, unquote_plus, urlsplit

#: `reps` d'un exercice **au temps**. La sentinelle vit dans le fichier et dans ce module,
#: jamais dans `exercise_log.csv` — `Reps` y est borné `ge=1`, et desserrer cette borne la
#: desserrerait aussi pour la saisie manuelle (**D3**).
#:
#: Une cellule à `-1` **dit** « cet exercice est au temps » ; une cellule vide laisserait
#: deviner, et deux lecteurs du fichier trancheraient différemment le jour où l'une des
#: deux colonnes est corrigée à la main.
TIMED = -1

#: Bornes de la spécification, §4. Le couple est `(min, max)`.
ROUNDS = (1, 99)
ROUND_REST_S = (0, 900)
DURATION_S = (1, 999)
REPS = (1, 999)
REST_S = (0, 999)

#: Replis de la spécification, §4 : ce que Cadence retient d'un champ absent ou illisible.
DEFAULT_NAME = "Workout"
DEFAULT_DURATION_S = 20
DEFAULT_REPS = 20

#: Estimation d'un exercice en répétitions, §7. Deux secondes par répétition, dix secondes
#: au minimum. Ces deux nombres sont ceux de Cadence : les changer ferait afficher à Metric
#: une durée que l'autre application contredit à l'écran suivant.
SECONDS_PER_REP = 2
MIN_REP_EXERCISE_S = 10

#: Les 35 noms exacts du catalogue de Cadence (§8). Ils ne décident **rien** au déroulé —
#: n'importe quel nom fonctionne — mais eux seuls affichent une illustration pendant le
#: repos qui précède l'exercice.
#:
#: La correspondance approximative de Cadence est un piège documenté : « Push-Ups » y
#: donne l'illustration de *Pike Push-ups*, c'est-à-dire un autre exercice. C'est pour ça
#: que cette liste est ici et non laissée à la mémoire de qui écrit une séance.
#:
#: `Dumbell Curl` et `Push Ups Wide Grip` sont les variantes orthographiques que Cadence
#: accepte ; elles sont dans la liste parce qu'un lien existant peut les porter, et la
#: forme correcte est juste à côté.
ILLUSTRATED: tuple[str, ...] = (
    "Bicycle Crunches",
    "Burpees",
    "Concentration Curl",
    "Crunchs",
    "Donkey Kicks",
    "Dumbbell Bent-Over Row",
    "Dumbbell Curl",
    "Dumbbell Goblet Squat",
    "Dumbbell Lateral Raise",
    "Dumbbell Romanian Deadlift",
    "Dumbbell Shoulder Press",
    "Dumbell Curl",
    "Flutter Kicks",
    "Glute Bridge",
    "Hammer Curl",
    "High Knees",
    "Hip Thrust",
    "Inchworm Walk",
    "Lunges",
    "Overhead Tricep Extension",
    "Pike Push-ups",
    "Plank",
    "Pull-ups",
    "Push Ups Wide Grip",
    "Push-Ups Classic",
    "Push-Ups Wide Grip",
    "Reverse Crunches",
    "Reverse Snow Angels",
    "Russian Twist",
    "Shoulder taps",
    "Side Plank",
    "Skater Jumps",
    "Superman",
    "Tricep Kickback",
    "V-ups",
)


@dataclass(frozen=True)
class LinkExercise:
    """Un exercice, tel que le lien le porte.

    `duration_s` n'est lu que si `reps == TIMED`. **`reps` fait autorité** : un fichier
    corrigé à la main peut porter les deux, et sans cette règle écrite le générateur de
    lien et l'estimateur de durée trancheraient différemment.
    """

    name: str
    duration_s: int = DEFAULT_DURATION_S
    reps: int = TIMED
    rest_s: int = 0

    @property
    def timed(self) -> bool:
        return self.reps == TIMED


@dataclass(frozen=True)
class LinkCircuit:
    """Une séance entière, telle que le lien la porte."""

    name: str
    rounds: int
    round_rest_s: int
    exercises: tuple[LinkExercise, ...]


@dataclass(frozen=True)
class Estimate:
    """Durée d'une séance, et si elle est une mesure ou un ordre de grandeur.

    `exact` est faux dès qu'un exercice est en répétitions : personne ne sait combien de
    temps prend une série. C'est ce booléen que l'écran traduit en `~` devant le total, et
    la spécification est catégorique — on n'annonce jamais une durée exacte dans ce cas.
    """

    minutes: float
    exact: bool


def _clamp(value: int, bounds: tuple[int, int]) -> int:
    low, high = bounds
    return max(low, min(high, value))


def normalise(circuit: LinkCircuit) -> LinkCircuit:
    """La séance telle que Cadence l'exécutera réellement.

    Toutes les valeurs sont ramenées dans leurs bornes, jamais rejetées : c'est le
    comportement de l'application cible, et le reproduire est ce qui garantit que la durée
    annoncée par Metric est celle qui se déroulera.
    """
    exercises = tuple(
        LinkExercise(
            name=exercise.name,
            duration_s=_clamp(exercise.duration_s, DURATION_S),
            reps=TIMED if exercise.timed else _clamp(exercise.reps, REPS),
            rest_s=_clamp(exercise.rest_s, REST_S),
        )
        for exercise in circuit.exercises
        if exercise.name.strip()
    )
    return LinkCircuit(
        name=circuit.name.strip() or DEFAULT_NAME,
        rounds=_clamp(circuit.rounds, ROUNDS),
        round_rest_s=_clamp(circuit.round_rest_s, ROUND_REST_S),
        exercises=exercises,
    )


def _encode(text: str) -> str:
    """Échappe un nom (§3).

    `quote` laisse le tilde intact — la plupart des implémentations le tiennent pour non
    réservé — et c'est précisément le caractère qui sépare deux segments. Le remplacement
    explicite n'est donc pas une ceinture de plus : sans lui, un exercice nommé
    « tempo ~ lent » couperait la séance en deux.
    """
    return quote(text, safe="").replace("~", "%7E").replace("%20", "+")


def build_url(base: str, circuit: LinkCircuit) -> str | None:
    """L'adresse à ouvrir, ou `None` quand aucune adresse de base n'est réglée.

    **`None` et pas une adresse relative.** Sans base, il n'y a pas de lien — c'est un
    état que l'écran sait dire (« adresse non renseignée »), là où un lien tronqué serait
    un bouton qui mène nulle part.

    Rend aussi `None` quand il ne reste aucun exercice nommé : la spécification dit qu'un
    tel lien ouvre l'écran d'accueil, ce qui n'est pas ce que l'utilisateur a demandé.
    """
    if not base.strip():
        return None

    ready = normalise(circuit)
    if not ready.exercises:
        return None

    segments = [_encode(ready.name), str(ready.rounds), str(ready.round_rest_s)]
    for exercise in ready.exercises:
        length = f"{exercise.duration_s}s" if exercise.timed else f"{exercise.reps}x"
        segments.append(f"{_encode(exercise.name)}:{length}:{exercise.rest_s}")

    return f"{base.strip()}?w=" + "~".join(segments)


def _whole(raw: str, fallback: int) -> int:
    """Entier d'un segment, avec repli. Un champ illisible ne perd pas la séance (§4)."""
    try:
        return int(raw.strip())
    except ValueError:
        return fallback


def _read_length(raw: str) -> tuple[int, int]:
    """Le champ de durée d'un exercice → `(duration_s, reps)`.

    Le suffixe `x` est ce qui distingue les deux, il est insensible à la casse, et le `s`
    est facultatif. Un piège de la spécification est reproduit tel quel : `0x` retombe sur
    vingt **répétitions** — la valeur est invalide, mais le suffixe reste, et le remplacer
    par vingt secondes changerait la nature de l'exercice.
    """
    cleaned = raw.strip()
    if cleaned[-1:].lower() == "x":
        reps = _whole(cleaned[:-1], 0)
        return DEFAULT_DURATION_S, reps if reps >= REPS[0] else DEFAULT_REPS

    if cleaned[-1:].lower() == "s":
        cleaned = cleaned[:-1]
    seconds = _whole(cleaned, 0)
    return (seconds if seconds >= DURATION_S[0] else DEFAULT_DURATION_S), TIMED


def _raw_param(url: str) -> str | None:
    """La valeur **non décodée** de `w`.

    `parse_qs` décoderait, et un `%7E` redeviendrait un `~` avant qu'on ait découpé les
    segments : un nom d'exercice contenant un tilde couperait alors la séance en deux. Les
    autres paramètres sont ignorés, comme le dit §9 — un `utm_source` collé au lien ne doit
    pas empêcher de le relire.
    """
    for part in urlsplit(url).query.split("&"):
        if part.startswith("w="):
            return part[2:]
    return None


def parse_url(url: str) -> LinkCircuit | None:
    """Relit un lien, ou `None` s'il n'en porte pas un d'exploitable.

    **Ne lève jamais.** Un lien invalide n'ouvre aucune erreur dans Cadence — il tombe sur
    l'écran d'accueil (§9) — et le décodeur reproduit cette tolérance : c'est l'appelant qui
    décide quoi en dire, et il n'a qu'un cas à traiter.
    """
    raw = _raw_param(url)
    if raw is None:
        return None

    segments = raw.split("~")
    if len(segments) < 4:
        return None

    exercises: list[LinkExercise] = []
    for segment in segments[3:]:
        fields = segment.split(":")
        name = unquote_plus(fields[0]).strip()
        # Un exercice anonyme est **ignoré**, et les autres sont gardés (§9). Refuser la
        # séance entière perdrait ce qui est lisible pour une cellule qui ne l'est pas.
        if not name:
            continue
        duration_s, reps = (
            _read_length(fields[1]) if len(fields) > 1 else (DEFAULT_DURATION_S, TIMED)
        )
        exercises.append(
            LinkExercise(
                name=name,
                duration_s=duration_s,
                reps=reps,
                rest_s=_whole(fields[2], 0) if len(fields) > 2 else 0,
            )
        )

    if not exercises:
        return None

    return normalise(
        LinkCircuit(
            name=unquote_plus(segments[0]).strip() or DEFAULT_NAME,
            rounds=_whole(segments[1], ROUNDS[0]),
            round_rest_s=_whole(segments[2], ROUND_REST_S[0]),
            exercises=tuple(exercises),
        )
    )


def find_in_text(text: str) -> str | None:
    """La première adresse de séance Cadence trouvée dans un texte libre, ou `None`.

    **C'est la condition du raccourci du planning** (**D5**), pas une entorse. La décision
    est que le lien vit dans la note de `plan.csv` — aucune colonne, aucun rattachement.
    Mais reconnaître une adresse Cadence dans du texte est une règle du format, et la
    laisser au client en ferait une seconde implémentation, à côté de celle-ci.

    Le filtre n'est pas « ça ressemble à une URL » : c'est `parse_url` qui tranche, donc
    exactement le même lecteur que partout ailleurs. Une adresse qui ne porte pas de séance
    lisible n'est pas rendue — l'écran ne proposera pas d'ouvrir un lien mort.
    """
    for candidate in re.findall(r"https?://\S+", text):
        cleaned = str(candidate).rstrip(".,;:!?)»\"'")
        if parse_url(cleaned) is not None:
            return cleaned
    return None


def estimate(circuit: LinkCircuit) -> Estimate:
    """Durée totale, et si elle se dit sans réserve (§7).

    Elle est calculée sur les valeurs **bornées** : annoncer 500 rounds quand Cadence en
    exécutera 99 serait faux d'un facteur cinq.
    """
    ready = normalise(circuit)
    if not ready.exercises:
        return Estimate(minutes=0.0, exact=True)

    seconds = 0
    exact = True
    for exercise in ready.exercises:
        if exercise.timed:
            seconds += exercise.duration_s
        else:
            exact = False
            seconds += max(exercise.reps * SECONDS_PER_REP, MIN_REP_EXERCISE_S)
        seconds += exercise.rest_s

    total = seconds * ready.rounds + ready.round_rest_s * (ready.rounds - 1)
    return Estimate(minutes=round(total / 60, 1), exact=exact)


__all__ = [
    "DEFAULT_NAME",
    "ILLUSTRATED",
    "TIMED",
    "Estimate",
    "LinkCircuit",
    "LinkExercise",
    "build_url",
    "estimate",
    "find_in_text",
    "normalise",
    "parse_url",
]
