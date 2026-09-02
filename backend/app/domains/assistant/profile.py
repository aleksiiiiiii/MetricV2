"""Le profil — ce que l'assistant sait de moi et qui ne change pas (`IA-10` a contrario).

## Pourquoi ce n'est pas le carnet

Le carnet porte ce que **j'ai dit** et il s'écrit tout seul : `IA-10` autorise l'assistant à
y ajouter une note parce qu'une note fausse ne casse aucun chiffre — elle change ce qu'il
croit savoir, et cela se lit et se corrige.

**Le profil ne suit pas cette règle.** Une taille fausse change toutes les charges qu'on en
déduit, un jour d'entraînement inventé change tout le planning proposé. Il est donc
**saisi**, jamais proposé : aucune action du catalogue ne l'écrit, et le modèle ne le reçoit
qu'en lecture. Ce n'est pas la même nature de donnée, elle ne suit pas la même règle.

## Pourquoi dans `settings.csv`

Ce clé/valeur est dégénéré exprès — « ajouter un réglage sans migration, et le corriger
dans un tableur sans connaître le schéma ». `update_keys` existe déjà pour les clés que
l'API ne type pas ; le domaine Notifications s'en sert pour ses créneaux. Un profil *est*
un réglage sur soi.

## Aucun défaut, et c'est la différence avec un objectif

Un poids cible non réglé retombe sur 70 kg parce qu'un objectif doit exister pour qu'un
écran ait quelque chose à montrer. Une taille non saisie n'a **pas** de repli : écrire
« 175 cm » parce que c'est courant serait une valeur inventée, et le modèle en déduirait des
charges. Une clé absente ne part pas dans la consigne — le bloc rétrécit, il ne se remplit
pas.
"""

from __future__ import annotations

from datetime import date

from app.core.dates import today_local
from app.core.text import fold

#: Clés portées par `settings/settings.csv`. Préfixées, parce qu'elles cohabitent avec les
#: cibles et les créneaux de rappel dans le même fichier — et qu'un `equipment` nu ne
#: dirait pas, dans un tableur, de quoi il est l'équipement.
HEIGHT = "profile_height_cm"
BIRTH_YEAR = "profile_birth_year"
EQUIPMENT = "profile_equipment"
TRAINING_DAYS = "profile_training_days"
PREFERENCES = "profile_preferences"

#: Ce qu'il ne faut **pas** me proposer — « pas de banc », « épaule droite sensible ».
#:
#: Une clé à part de `PREFERENCES`, et la distinction porte tout le sens : une préférence
#: se contourne — « j'aime finir par du gainage » n'interdit rien — là où une contrainte
#: est un refus. Les mélanger dans un seul champ libre ôte au modèle le moyen de savoir
#: laquelle il a le droit d'ignorer, et le seul cas où ça se voit est celui où ça coûte le
#: plus cher : une épaule.
CONSTRAINTS = "profile_constraints"

KEYS: tuple[str, ...] = (
    HEIGHT,
    BIRTH_YEAR,
    EQUIPMENT,
    TRAINING_DAYS,
    PREFERENCES,
    CONSTRAINTS,
)

#: Le séparateur de la liste de matériel dans la cellule.
#:
#: La virgule et non le point-virgule d'`ExerciseRow.aliases` : les 28 valeurs du catalogue
#: n'en contiennent aucune — elles contiennent des **espaces** (`body weight`, `ez
#: barbell`), ce qui interdisait l'espace comme séparateur. C'est aussi ce que
#: `hydration_presets_ml` écrit déjà dans ce fichier, et une seconde convention dans le
#: même CSV serait une devinette de plus à l'ouvrir dans un tableur.
EQUIPMENT_SEPARATOR = ","

#: Longueur d'un champ libre. Le profil part dans **chaque** question, avant même le
#: condensé : trois paragraphes de préférences coûteraient à chaque tour ce qu'une phrase
#: suffit à dire.
MAX_FREE = 300

#: Bornes de vraisemblance, larges à dessein. Elles n'existent pas pour juger une saisie
#: mais pour empêcher qu'une faute de frappe — 1780 au lieu de 178 — devienne une donnée que
#: le modèle prendra au sérieux.
MIN_HEIGHT_CM = 100
MAX_HEIGHT_CM = 250
MIN_BIRTH_YEAR = 1900


def _whole(raw: str) -> int | None:
    """Entier lisible, ou `None`. Une cellule abîmée vaut une absence, jamais une erreur.

    C'est la règle du module de réglages, reprise telle quelle : le fichier est modifiable
    à la main, une valeur cassée y est une possibilité normale, et elle doit coûter son
    propre repli — pas un écran.
    """
    try:
        return int(float(raw.strip().replace(",", ".")))
    except (ValueError, AttributeError):
        return None


def equipment(raw: str) -> tuple[list[str], list[str]]:
    """La cellule « matériel » → `(reconnus, non reconnus)`, dans l'ordre du catalogue.

    ## Pourquoi les non reconnus sont **rendus** et non jetés

    Ce champ était libre avant la phase 3 : la cellule d'un profil existant porte une
    phrase — « dumbbels 10kg et tapis ». La fermer sur les 28 valeurs du catalogue sans
    rien dire ferait disparaître cette phrase du profil au premier affichage, sans que
    personne ne l'ait effacée. C'est exactement ce que l'invariant interdit dans l'autre
    sens : une donnée ne s'invente pas, et elle ne s'évapore pas non plus.

    L'écran les montre donc, et invite à recocher. **Le modèle, lui, ne les reçoit pas** :
    « matériel » veut maintenant dire « une liste du catalogue », et lui servir une phrase
    à côté lui ferait croire à deux sortes de matériel dont une seule filtre le catalogue.

    ## Le rapprochement est exact, jamais approximatif

    `fold` ramène la casse et les accents — rien de plus. « Dumbbell » retrouve
    `dumbbell` ; « dumbbels » ne retrouve rien, et c'est le comportement voulu : un
    rapprochement flou choisirait à la place de l'utilisateur, et son erreur ne se verrait
    pas — elle ferait simplement disparaître des exercices de ce qu'on lui propose.
    """
    from app.domains.activity import exercise_catalog

    known = {fold(name): name for name in exercise_catalog.catalog().equipment}
    seen: set[str] = set()
    found: list[str] = []
    unknown: list[str] = []

    for chunk in raw.split(EQUIPMENT_SEPARATOR):
        cleaned = chunk.strip()
        if not cleaned:
            continue
        name = known.get(fold(cleaned))
        if name is None:
            unknown.append(cleaned)
        elif name not in seen:
            seen.add(name)
            found.append(name)

    # L'ordre du catalogue et non celui de la cellule : deux enregistrements successifs
    # doivent produire la même ligne de consigne, sinon le cache de préfixe du modèle
    # se casse sur un simple changement d'ordre de cases cochées.
    order = {name: index for index, name in enumerate(exercise_catalog.catalog().equipment)}
    found.sort(key=lambda name: order[name])
    return found, unknown


def height_cm(raw: str) -> int | None:
    value = _whole(raw)
    return value if value is not None and MIN_HEIGHT_CM <= value <= MAX_HEIGHT_CM else None


def age(raw: str, *, today: date | None = None) -> int | None:
    """Âge en années, **calculé ici** à partir de l'année de naissance.

    On range l'année et non l'âge, pour la raison qui vaut partout : un âge stocké est faux
    au premier anniversaire, et personne ne pense à le corriger. C'est aussi pourquoi ce
    calcul est au serveur et non à l'écran — le client formate, il ne dérive pas.
    """
    year = _whole(raw)
    current = today or today_local()
    if year is None or not MIN_BIRTH_YEAR <= year <= current.year:
        return None
    return current.year - year


def lines(settings: dict[str, str], *, today: date | None = None) -> list[str]:
    """Le bloc « Ce que je suis », une ligne par élément renseigné.

    **Rien n'est servi pour une clé absente ou illisible.** Le bloc rétrécit jusqu'à
    disparaître ; il ne se remplit jamais d'un « non renseigné » qui occuperait la place
    sans rien apprendre, ni d'un défaut qui mentirait.
    """
    out: list[str] = []

    taille = height_cm(settings.get(HEIGHT, ""))
    if taille is not None:
        out.append(f"Taille : {taille} cm")

    ans = age(settings.get(BIRTH_YEAR, ""), today=today)
    if ans is not None:
        out.append(f"Âge : {ans} ans")

    jours = settings.get(TRAINING_DAYS, "").strip()
    if jours:
        out.append(f"Jours où je peux m'entraîner : {jours[:MAX_FREE]}")

    materiel, _inconnus = equipment(settings.get(EQUIPMENT, ""))
    if materiel:
        # Les noms **du catalogue**, en anglais et non traduits. C'est avec eux que le
        # modèle cherche un exercice (`exercices_cadence`) : les rendre en français ici
        # l'obligerait à retraduire pour chercher, et c'est précisément la traduction
        # aller-retour qui fabrique un nom que le catalogue ne porte pas.
        out.append(f"Matériel dont je dispose : {', '.join(materiel)}")

    for key, label in (
        (PREFERENCES, "Préférences d'entraînement"),
        # **En dernier, et nommée pour ce qu'elle est.** Une contrainte n'est pas un
        # souhait : la phrase « à respecter » est ce qui dit au modèle qu'il n'a pas le
        # droit de l'arbitrer contre autre chose.
        (CONSTRAINTS, "Contraintes à respecter"),
    ):
        value = settings.get(key, "").strip()
        if value:
            out.append(f"{label} : {value[:MAX_FREE]}")

    return out


__all__ = [
    "BIRTH_YEAR",
    "CONSTRAINTS",
    "EQUIPMENT",
    "EQUIPMENT_SEPARATOR",
    "HEIGHT",
    "KEYS",
    "MAX_FREE",
    "PREFERENCES",
    "TRAINING_DAYS",
    "age",
    "equipment",
    "height_cm",
    "lines",
]
