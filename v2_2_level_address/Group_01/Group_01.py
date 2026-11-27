# Change your team name to Group_xx
TEAM_NAME = 'Group_01'


# NOTE: you CAN change this cell
# If you want to use your own database, download it here
# !gdown ...


# NOTE: you CAN change this cell
# Add more to your needs
# you must place ALL pip install here


# NOTE: you CAN change this cell
# import your library here
import json
import random
import re
import time
import unicodedata
from collections import defaultdict
from itertools import combinations, product
from pathlib import Path


# NOTE: you MUST change this cell
# New methods / functions must be written under class Solution.
class Solution:
    FIELDS = ("street", "ward", "province")
    STREET, WARD, PROVINCE = range(len(FIELDS))
    EXACT_NAME_SCORE = 23
    JOINED_NAME_SCORE = 16
    INITIALS_SCORE = 12
    MIN_RETAINED_PERCENT = 40
    WARD_PROVINCE_HINTS = {
        "Cẩm Lệ": "Đà Nẵng",
        "Cửa Lò": "Nghệ An",
        "Chí Linh": "Hải Phòng",
    }
    MARKERS = (
        ("đường", 0),
        ("duong", 0),
        ("phố", 0),
        ("pho", 0),
        ("đg", 0),
        ("dg", 0),
        ("đ", 0),
        ("d", 0),
        ("phường", 1),
        ("phuong", 1),
        ("xã", 1),
        ("xa", 1),
        ("đặc khu", 1),
        ("dac khu", 1),
        ("thị trấn", 1),
        ("thi tran", 1),
        ("p", 1),
        ("x", 1),
        ("tt", 1),
        ("thành phố", 2),
        ("thanh pho", 2),
        ("tỉnh", 2),
        ("tinh", 2),
        ("tp", 2),
        ("t", 2),
    )
    OTHER_LEVELS = {
        ("quận",),
        ("quan",),
        ("huyện",),
        ("huyen",),
        ("thị", "xã"),
        ("thi", "xa"),
        ("khu", "phố"),
        ("khu", "pho"),
        ("thôn",),
        ("thon",),
        ("ấp",),
        ("ap",),
        ("bản",),
        ("ban",),
    }
    CITY_INITIALS = re.compile(r"(?<![\w.])t\s*\.\s*p\s*\.?(?!\w)", re.IGNORECASE)
    DOTTED_PAIR = re.compile(r"(?<![\w.])([^\W\d_])\.([^\W\d_])\.(?!\w)")
    INITIAL_RUN = re.compile(
        r"(?<![\w.])(?:(?P<province>tp\.)?(?P<dotted>(?:[^\W\d_]\.){1,7}[^\W\d_]\.?)"
        r"|(?P<compact>[^\W\d_]{2,8}))(?![\w.])",
        re.IGNORECASE,
    )
    ROUTE_INPUT = re.compile(
        r"(?<!\w)(?:qu[ốôo]c[ .\t-]*l[ộôo]|q[ .\t-]*l)[ .\t-]*"
        r"(?P<code>[0-9]+[a-z0-9]*)(?!\w)",
        re.IGNORECASE,
    )
    ROUTE_TOKEN = re.compile(r"ql[0-9]+[a-z0-9]*")
    PROVINCE_ALIASES = {
        "hcm": "Hồ Chí Minh",
        "hcmc": "Hồ Chí Minh",
        "tphcm": "Hồ Chí Minh",
        "sg": "Hồ Chí Minh",
        "sai gon": "Hồ Chí Minh",
        "hn": "Hà Nội",
    }
    TOKEN = re.compile(r"\d+(?:/\d+)+[^\W\d_]?|[^\W_]+", re.UNICODE)
    SEPARATORS = re.compile(r"[,;|\n]+|\s+[-–]\s+")
    HOUSE_NUMBER = re.compile(r"\d+(?:/\d+)*[a-zđ]?")

    def __init__(
        self,
        list_province: list[str],
        list_ward: list[str],
        list_street: list[str],
        *,
        address_links=(),
        random_seed=None,
    ):
        self.list_province = list_province
        self.list_ward = list_ward
        self.list_street = list_street
        self._rng = random.Random(random_seed)
        self._provinces_by_ward = defaultdict(set)
        self._links_by_field = [defaultdict(set) for _ in self.FIELDS]
        for link in address_links:
            names = tuple(link[field] for field in self.FIELDS)
            ward, province = names[self.WARD], names[self.PROVINCE]
            if ward and province:
                self._provinces_by_ward[ward].add(province)
            for field, name in enumerate(names):
                if name:
                    self._links_by_field[field][name].add(names)

        self._routes_by_code = defaultdict(set)
        self._exact_names = defaultdict(set)
        self._accentless_names = defaultdict(set)
        self._joined_names = defaultdict(set)
        self._names_by_initials = defaultdict(set)
        self._common_aliases = defaultdict(set)
        self._names_by_missing_word = defaultdict(set)
        self._exact_names_by_missing_word = defaultdict(set)
        self._deletion_tries = [defaultdict(dict) for _ in self.FIELDS]
        self._names_by_fuzzy_key = defaultdict(set)
        self._one_edit_index = defaultdict(set)
        self._two_edit_index = defaultdict(set)
        self._streets_with_admin_prefix = defaultdict(set)
        self._max_name_words = 1

        self._markers = tuple(
            (tuple(marker.split()), field) for marker, field in self.MARKERS
        )
        self._joined_markers = tuple(
            ("".join(marker), field)
            for marker, field in self._markers
            if len(marker) > 1
        )
        self._field_by_marker = dict(self._markers)
        self._separate_markers = self._field_by_marker.keys()

        names_by_field = (list_street, list_ward, list_province)
        for field, names in enumerate(names_by_field):
            for name in names:
                self._index_name(name.strip(), field)

        for alias, province in self.PROVINCE_ALIASES.items():
            entries = self._exact_names.get(tuple(self._tokenize(province)), ())
            self._common_aliases[alias.replace(" ", "")].update(
                entry for entry in entries if entry[0] == self.PROVINCE
            )

    def process(self, s: str) -> dict[str, str]:
        address = unicodedata.normalize("NFC", s)
        address = self.ROUTE_INPUT.sub(
            lambda match: "ql" + match.group("code").casefold(),
            address,
        )

        context_labels = None
        if any(self._links_by_field):
            context_labels = self._resolve_abbreviations_with_context(address)
            if context_labels is None:
                context_labels = self._resolve_deletions_with_context(address)
            if context_labels is not None and all(context_labels):
                return dict(zip(self.FIELDS, context_labels))

        labels = self._parse_address(address, context_labels)
        return dict(zip(self.FIELDS, labels))

    def _index_name(self, name, field):
        words = tuple(self._tokenize(name))
        if not words:
            return

        entry = (field, name)
        folded_name = self._strip_diacritics(" ".join(words))
        compact_name = folded_name.replace(" ", "")
        word_count = len(words)
        self._max_name_words = max(self._max_name_words, word_count)
        self._exact_names[words].add(entry)
        self._accentless_names[folded_name].add(entry)
        self._joined_names[compact_name].add(entry)
        self._index_abbreviations(folded_name.split(), entry)

        if field == self.STREET:
            route = self.ROUTE_INPUT.fullmatch(unicodedata.normalize("NFC", name))
            if route is not None:
                route_code = "ql" + route.group("code").casefold()
                self._routes_by_code[route_code].add(name)

            folded_words = folded_name.split()
            for prefix_length in (1, 2):
                prefix = tuple(folded_words[:prefix_length])
                if word_count > prefix_length and prefix in self.OTHER_LEVELS:
                    self._streets_with_admin_prefix[prefix].add(
                        (word_count, folded_name)
                    )
        for index in range(1, word_count - 1):
            if words[index].isalpha():
                shortened = " ".join(words[:index] + words[index + 1 :])
                self._exact_names_by_missing_word[shortened].add(entry)
                self._names_by_missing_word[self._strip_diacritics(shortened)].add(
                    entry
                )

        letter_count = sum(char.isalpha() for char in folded_name)
        if len(compact_name) >= 3 and letter_count:
            length = len(compact_name)
            numbers = tuple(re.findall(r"\d+", compact_name))
            node = self._deletion_tries[field][numbers].setdefault(length, {})
            for letter in compact_name:
                node = node.setdefault(letter, {})
            node.setdefault("", []).append((name, word_count))
        if letter_count >= 2:
            self._names_by_fuzzy_key[folded_name].add(entry)
            one_edit_signatures = self._deletion_keys(folded_name)
            for signature in one_edit_signatures:
                self._one_edit_index[signature].add(folded_name)

            if len(compact_name) >= 8 or (
                field == self.WARD and len(compact_name) >= 5
            ):
                two_edit_signatures = {
                    shorter
                    for signature in one_edit_signatures
                    for shorter in self._deletion_keys(signature)
                }
                for signature in two_edit_signatures:
                    self._two_edit_index[signature].add(folded_name)

    def _index_abbreviations(self, words, entry):
        if len(words) < 2 or any(not word.isalpha() for word in words):
            return
        compact = "".join(words)
        initials = "".join(word[0] for word in words)
        self._names_by_initials[initials].add(entry)
        for count in range(1, min(3, len(words) - 1) + 1):
            for selected in combinations(range(len(words)), count):
                for lengths in product((1, 2), repeat=count):
                    shortened = list(words)
                    for index, length in zip(selected, lengths):
                        shortened[index] = words[index][:length]
                    alias = "".join(shortened)
                    if alias != compact:
                        self._names_by_initials[alias].add(entry)

    @staticmethod
    def _deletion_keys(key):
        return {key} | {key[:index] + key[index + 1 :] for index in range(len(key))}

    def _parse_address(self, address, context_labels):
        dotted_initials = set()

        def join_initials(match):
            initials = "".join(match.groups()).casefold()
            dotted_initials.add(initials)
            return initials

        address = self.CITY_INITIALS.sub("tp ", address)
        address = self.DOTTED_PAIR.sub(join_initials, address)
        words, boundaries = self._split_address(address)
        candidates = self._find_candidates(words, boundaries)

        known_labels = self._select_segmentation(candidates)
        if context_labels is not None:
            known_labels = tuple(
                contextual or textual
                for contextual, textual in zip(context_labels, known_labels)
            )
        if all(known_labels):
            return known_labels

        if any(self._links_by_field) and any(known_labels):
            for index, word in enumerate(words):
                if word not in dotted_initials:
                    continue
                has_marker = any(
                    tuple(words[index - length : index]) in self._separate_markers
                    for length in (1, 2)
                    if index >= length
                    and not any(index - length < end <= index for end in boundaries)
                )
                if has_marker:
                    continue
                for field, label in self._names_by_initials.get(
                    self._strip_diacritics(word), ()
                ):
                    if not known_labels[field] and self._supported_by_geography(
                        field, label, known_labels
                    ):
                        candidates[index].append((index + 1, field, label, 15))
        self._add_deletion_candidates(words, boundaries, candidates, known_labels)

        known_province = known_labels[self.PROVINCE]
        compatible_candidates = [
            [
                (end, field, label, score)
                for end, field, label, score in options
                if (not known_labels[field] or label == known_labels[field])
                and (
                    field != self.WARD
                    or known_labels[self.WARD]
                    or not known_province
                    or self.WARD_PROVINCE_HINTS.get(label, known_province)
                    == known_province
                )
            ]
            for options in candidates
        ]
        selected = self._select_segmentation(
            compatible_candidates, known_labels, randomize=True
        )
        return tuple(known or chosen for known, chosen in zip(known_labels, selected))

    def _split_address(self, address):
        words = []
        boundaries = []
        for part in self.SEPARATORS.split(address):
            for component in self._remove_other_levels(self._tokenize(part)):
                words.extend(component)
                boundaries.append(len(words))
        return words, boundaries

    @classmethod
    def _tokenize(cls, text):
        text = unicodedata.normalize("NFC", text).casefold()
        return cls.TOKEN.findall(text)

    @staticmethod
    def _strip_diacritics(text):
        return "".join(
            char
            for char in unicodedata.normalize("NFD", text.replace("đ", "d"))
            if not unicodedata.combining(char)
        )

    def _find_field_markers(self, words, index, limit):
        word = words[index]
        for marker, field in self._joined_markers:
            if word == marker and index + 1 < limit:
                yield index + 1, None, field, True
            elif word.startswith(marker) and len(word) > len(marker):
                yield index, word[len(marker) :], field, True
        for marker, field in self._markers:
            last = index + len(marker) - 1
            if last >= limit or tuple(words[index:last]) != marker[:-1]:
                continue
            word = words[last]
            if word == marker[-1] and last + 1 < limit:
                yield last + 1, None, field, True
            elif word.startswith(marker[-1]) and len(word) > len(marker[-1]):
                yield last, word[len(marker[-1]) :], field, len(marker[-1]) > 1

    def _remove_other_levels(self, tokens):
        tokens = tuple(tokens)
        folded = tuple(self._strip_diacritics(word) for word in tokens)
        start = index = 0
        while index + 1 < len(tokens):
            size = 2 if tokens[index : index + 2] in self.OTHER_LEVELS else 0
            if not size and (
                tokens[index : index + 1] in self.OTHER_LEVELS
                or (tokens[index] in {"q", "h"} and index == start)
                or (tokens[index] in {"tổ", "to"} and tokens[index + 1].isdigit())
            ):
                size = 1
            if not size:
                index += 1
                continue

            inside_name = any(
                " ".join(folded[left:right]) in self._accentless_names
                for left in range(max(start, index - self._max_name_words + 1), index)
                for right in range(
                    index + 1, min(len(tokens), left + self._max_name_words) + 1
                )
            )
            follows_target = any(
                tokens[index - length : index] in self._separate_markers
                for length in (1, 2)
                if index >= start + length
            )
            remaining_is_name = index == start and tokens[start:] in self._exact_names
            if (
                inside_name
                or follows_target
                or remaining_is_name
                or self._looks_like_street_with_level_prefix(folded, index, size)
            ):
                index += 1
                continue

            if start < index:
                yield tokens[start:index]
            name_start = index + size
            boundary = next(
                (
                    end
                    for end in range(name_start + 1, len(tokens))
                    if self._starts_known_component(tokens, end)
                ),
                len(tokens),
            )
            if name_start < boundary and self.HOUSE_NUMBER.fullmatch(
                tokens[name_start]
            ):
                boundary = name_start + 1
            else:
                for end in range(
                    min(boundary, name_start + self._max_name_words), name_start, -1
                ):
                    if " ".join(folded[name_start:end]) in self._accentless_names:
                        boundary = end
                        break
            start = index = boundary
        if start < len(tokens):
            yield tokens[start:]

    def _starts_known_component(self, words, index):
        for name_start, first, _, _ in self._find_field_markers(
            words, index, len(words)
        ):
            if first is None and (name_start - index > 1 or len(words[index]) > 1):
                return True
            for end in range(
                name_start + 1, min(len(words), name_start + self._max_name_words) + 1
            ):
                name = words[name_start:end]
                if first is not None:
                    name = (first, *name[1:])
                if self._strip_diacritics(" ".join(name)) in self._accentless_names:
                    return True
        return False

    def _looks_like_street_with_level_prefix(self, words, index, size):
        prefix = words[index : index + size]
        if not any(
            " ".join(words[left:index]) in self._accentless_names
            for left in range(max(0, index - self._max_name_words), index)
        ):
            return False
        for length, key in self._streets_with_admin_prefix.get(prefix, ()):
            end = index + length
            if not any(
                " ".join(words[end:right]) in self._accentless_names
                for right in range(
                    end + 1, min(len(words), end + self._max_name_words) + 1
                )
            ):
                continue
            if self._edit_distance(" ".join(words[index:end]), key) <= 1:
                return True
        return False

    def _find_candidates(self, words, boundaries):
        component_limits = []
        component_start = 0
        for component_end in boundaries:
            component_limits.extend([component_end] * (component_end - component_start))
            component_start = component_end

        markers_by_position = [
            tuple(self._find_field_markers(words, position, limit))
            for position, limit in enumerate(component_limits)
        ]
        scores_by_position = [{} for _ in words]
        spans_to_retry = []
        fields_starting_at = [set() for _ in range(len(words) + 1)]
        fields_ending_at = [set() for _ in range(len(words) + 1)]

        for position, component_end in enumerate(component_limits):
            begins_component = position == 0 or position in boundaries
            follows_house_number = position > 0 and bool(
                self.HOUSE_NUMBER.fullmatch(words[position - 1])
            )
            field_markers = markers_by_position[position]
            name_starts = ((position, None, None, True),) + field_markers
            for name_start, first_word, field_hint, allow_fuzzy in name_starts:
                max_end = min(component_end, name_start + self._max_name_words + 1)
                for end in range(name_start + 1, max_end + 1):
                    span = tuple(words[name_start:end])
                    if first_word is not None:
                        span = (first_word, *span[1:])
                    if (
                        field_hint is None
                        and end < component_end
                        and span in self._separate_markers
                    ):
                        continue

                    followed_by_marker = end < component_end and any(
                        remainder is None
                        for _, remainder, _, _ in markers_by_position[end]
                    )
                    right_boundary = end == component_end or followed_by_marker
                    anchored = (
                        begins_component
                        or follows_house_number
                        or field_hint is not None
                    )
                    boundary_bonus = (
                        3 * len(span)
                        + 2 * right_boundary
                        + 9 * (field_hint is not None)
                        + int(begins_component)
                        + 10 * (anchored and end == component_end)
                    )

                    ward_abbreviation = (
                        field_hint is None
                        and len(span) == 2
                        and self._field_by_marker.get(span[:1]) == self.WARD
                        and span[1].isalpha()
                        and len(span[1]) == 2
                        and sum(
                            field == self.WARD
                            for field, _ in self._names_by_initials.get(
                                self._strip_diacritics(span[1]), ()
                            )
                        )
                        > 1
                    )
                    found = False
                    for (field, label), quality in self._name_matches(
                        span, field_hint, anchored, right_boundary
                    ):
                        if (
                            ward_abbreviation
                            and field != self.WARD
                            and quality < self.JOINED_NAME_SCORE
                        ):
                            continue
                        if (
                            first_word is not None
                            and not allow_fuzzy
                            and quality < self.JOINED_NAME_SCORE
                        ):
                            continue
                        found = True
                        house_number_bonus = int(
                            follows_house_number and field == self.STREET
                        )
                        candidate = (end, field, label)
                        scores = scores_by_position[position]
                        scores[candidate] = max(
                            quality + boundary_bonus + house_number_bonus,
                            scores.get(candidate, 0),
                        )
                        if quality >= self.JOINED_NAME_SCORE:
                            fields_starting_at[position].add(field)
                            fields_ending_at[end].add(field)
                    if not found and allow_fuzzy and not ward_abbreviation:
                        spans_to_retry.append(
                            (
                                position,
                                end,
                                span,
                                field_hint,
                                anchored,
                                right_boundary,
                                boundary_bonus,
                            )
                        )

        self._retry_fuzzy_spans(
            spans_to_retry, fields_ending_at, fields_starting_at, scores_by_position
        )
        return [
            [
                (end, field, label, score)
                for (end, field, label), score in scores.items()
            ]
            for scores in scores_by_position
        ]

    def _name_matches(
        self, words, field_hint, anchored, right_boundary, fuzzy=False, extra_edit=False
    ):
        if any(self.ROUTE_TOKEN.fullmatch(word) for word in words):
            if len(words) == 1 and field_hint in (None, self.STREET):
                return [
                    ((self.STREET, name), self.EXACT_NAME_SCORE)
                    for name in self._routes_by_code.get(words[0], ())
                ]
            return []
        text = " ".join(words)
        key = self._strip_diacritics(text)
        compact = key.replace(" ", "")
        scores = {}
        for entries, quality in (
            (self._exact_names.get(words, ()), self.EXACT_NAME_SCORE),
            (self._accentless_names.get(key, ()), 19),
            (self._joined_names.get(compact, ()), self.JOINED_NAME_SCORE),
            (self._common_aliases.get(compact, ()), 15),
            (self._names_by_initials.get(compact, ()), self.INITIALS_SCORE),
            (self._exact_names_by_missing_word.get(text, ()), 10),
            (self._names_by_missing_word.get(key, ()), 9),
        ):
            for entry in entries:
                field, label = entry
                if field_hint is not None and field != field_hint:
                    continue
                if label.isdigit() and field_hint != 0:
                    continue
                if quality == self.INITIALS_SCORE and (
                    not anchored
                    or not right_boundary
                    or (len(compact) < 3 and field_hint is None)
                ):
                    continue
                if quality in (9, 10, 15) and not (anchored and right_boundary):
                    continue
                scores.setdefault(entry, quality)

        min_letters = 2 if field_hint is not None else 4
        if fuzzy and not scores and sum(char.isalpha() for char in key) >= min_letters:
            max_edits = 2 if extra_edit and len(compact) >= 10 else 1
            scores.update(self._fuzzy_matches(text, key, max_edits, field_hint))
            if (
                not scores
                and extra_edit
                and field_hint == self.WARD
                and 6 <= len(compact) < 10
            ):
                scores.update(
                    self._fuzzy_matches(text, key, 2, field_hint, extra_letters=True)
                )
        return scores.items()

    def _retry_fuzzy_spans(
        self, spans, fields_ending_at, fields_starting_at, scores_by_position
    ):
        for (
            position,
            end,
            words,
            field_hint,
            anchored,
            right_boundary,
            boundary_bonus,
        ) in spans:
            left_fields = fields_ending_at[position]
            right_fields = fields_starting_at[end]
            if not (anchored or left_fields) or not (right_boundary or right_fields):
                continue

            search_field = field_hint
            if search_field is None and left_fields and right_fields:
                neighbor_fields = left_fields | right_fields
                if len(neighbor_fields) == 2 and left_fields != right_fields:
                    search_field = next(
                        iter({self.STREET, self.WARD, self.PROVINCE} - neighbor_fields)
                    )
            if (
                search_field is None
                and not (anchored and right_boundary)
                and len(words) < 2
            ):
                continue

            extra_edit = anchored and right_boundary and len(words) >= 2
            for (field, label), quality in self._name_matches(
                words, search_field, True, True, fuzzy=True, extra_edit=extra_edit
            ):
                if quality >= self.JOINED_NAME_SCORE:
                    continue
                other_left_fields = left_fields - {field}
                other_right_fields = right_fields - {field}
                if not anchored and not other_left_fields:
                    continue
                if not right_boundary and not other_right_fields:
                    continue

                neighbor_bonus = 13 if other_left_fields and other_right_fields else 0
                candidate = (end, field, label)
                scores = scores_by_position[position]
                scores[candidate] = max(
                    quality + boundary_bonus + neighbor_bonus,
                    scores.get(candidate, 0),
                )

    def _fuzzy_matches(self, text, key, max_edits, field_hint, *, extra_letters=False):
        signatures = self._deletion_keys(key)
        index = self._one_edit_index
        if max_edits == 2:
            signatures = {
                part
                for signature in signatures
                for part in self._deletion_keys(signature)
            }
            index = self._two_edit_index
        keys = set()
        for signature in signatures:
            keys.update(index.get(signature, ()))
        digits = re.findall(r"\d+", key)
        for candidate in keys:
            if (
                abs(len(key) - len(candidate)) > max_edits
                or (
                    extra_letters
                    and (
                        len(key) - len(candidate) != 2
                        or len(candidate.split()) != len(key.split())
                    )
                )
                or (
                    field_hint is None and sum(char.isalpha() for char in candidate) < 5
                )
                or re.findall(r"\d+", candidate) != digits
                or abs(len(key.split()) - len(candidate.split())) > 1
            ):
                continue
            distance = self._edit_distance(key, candidate)
            if 0 < distance <= max_edits:
                entries = [
                    entry
                    for entry in self._names_by_fuzzy_key[candidate]
                    if field_hint is None or entry[0] == field_hint
                ]
                quality = 13 - 5 * distance
                if text != key and len(entries) > 1:
                    accented_distances = {
                        entry: self._edit_distance(
                            text, " ".join(self._tokenize(entry[1]))
                        )
                        for entry in entries
                    }
                    closest = min(accented_distances.values())
                    for entry, accented_distance in accented_distances.items():
                        yield entry, quality + int(accented_distance == closest)
                else:
                    for entry in entries:
                        yield entry, quality

    @staticmethod
    def _edit_distance(left, right):
        older = None
        previous = list(range(len(right) + 1))
        for i, char in enumerate(left, start=1):
            current = [i]
            for j, other in enumerate(right, start=1):
                cost = min(
                    previous[j] + 1,
                    current[j - 1] + 1,
                    previous[j - 1] + (char != other),
                )
                if i > 1 and j > 1 and char == right[j - 2] and left[i - 2] == other:
                    cost = min(cost, older[j - 2] + 1)
                current.append(cost)
            older, previous = previous, current
        return previous[-1]

    def _add_deletion_candidates(self, words, boundaries, candidates, anchors):
        highest = {}
        for choices in candidates:
            for _, field, label, score in choices:
                if label == anchors[field]:
                    highest[field] = max(score, highest.get(field, 0))
        fixed = [
            (start, end)
            for start, choices in enumerate(candidates)
            for end, field, label, score in choices
            if label == anchors[field] and score == highest.get(field)
        ]
        occupied = {
            position for left, right in fixed for position in range(left, right)
        }
        fixed_starts = {left for left, _ in fixed}
        fixed_ends = {right for _, right in fixed}
        start = 0
        for end in boundaries:
            markers = {
                index: [
                    (name, first, field)
                    for name, first, field, valid in self._find_field_markers(
                        words, index, end
                    )
                    if valid
                    and (first is None or index == start or index in fixed_ends)
                ]
                for index in range(start, end)
                if index not in occupied
            }
            cuts = sorted(
                fixed_starts
                | {end}
                | {index for index, hints in markers.items() if hints}
            )
            for index in range(start, end):
                if index in occupied:
                    continue
                possibilities = markers.get(index, ())
                if not possibilities and (
                    index == start
                    or index in fixed_ends
                    or (index > start and self.HOUSE_NUMBER.fullmatch(words[index - 1]))
                ):
                    possibilities = [(index, None, None)]
                stop = next(cut for cut in cuts if cut > index)
                for name_start, first, field in possibilities:
                    if name_start >= stop or any(
                        pos in occupied for pos in range(name_start, stop)
                    ):
                        continue
                    span = tuple(words[name_start:stop])
                    if first is not None:
                        span = (first, *span[1:])
                    for target, label, score in self._deletion_matches(
                        span, field, anchors
                    ):
                        candidates[index].append((stop, target, label, score))
            start = end

    def _deletion_matches(self, span, field_hint, anchors):
        """Tìm tên chứa các chữ còn lại theo đúng thứ tự."""
        if any(self.ROUTE_TOKEN.fullmatch(word) for word in span):
            return []
        retained = "".join(self._strip_diacritics(word) for word in span)
        minimum = 2 if field_hint is not None else 3
        if len(retained) < minimum or not any(char.isalpha() for char in retained):
            return []
        retained_length = len(retained)
        numbers = tuple(re.findall(r"\d+", retained))
        fields = (field_hint,) if field_hint is not None else range(len(self.FIELDS))
        matches = []
        for field in fields:
            if anchors[field]:
                continue
            for label, word_count, name_length in self._find_retained_names(
                retained, field, numbers
            ):
                geographically_supported = self._supported_by_geography(
                    field, label, anchors
                )
                if field_hint is None and not geographically_supported:
                    continue
                proportion = 6 * retained_length // name_length
                score = 7 + proportion + int(len(span) == word_count)
                matches.append((field, label, score, geographically_supported))
        if any(match[3] for match in matches):
            matches = [match for match in matches if match[3]]
        return [(field, label, score) for field, label, score, _ in matches]

    def _find_retained_names(self, retained, field, numbers):
        retained_length = len(retained)
        max_length = 100 * retained_length // self.MIN_RETAINED_PERCENT
        tries_by_length = self._deletion_tries[field].get(numbers, {})
        for name_length, root in tries_by_length.items():
            if not retained_length < name_length <= max_length:
                continue
            stack = [(root, 0, name_length - retained_length)]
            while stack:
                node, matched, skips_left = stack.pop()
                if matched == retained_length and not skips_left:
                    for label, word_count in node.get("", ()):
                        yield label, word_count, name_length
                    continue

                # Chữ khớp sớm nhất vẫn để lại nhiều lựa chọn nhất cho phần sau.
                next_letter = retained[matched] if matched < retained_length else None
                child = node.get(next_letter)
                if child is not None:
                    stack.append((child, matched + 1, skips_left))
                if skips_left:
                    for letter, child in node.items():
                        if letter and letter != next_letter:
                            stack.append((child, matched, skips_left - 1))

    def _select_segmentation(
        self, candidates, anchors=None, *, with_score=False, randomize=False
    ):
        """Chọn các đoạn không chồng lấn. Mỗi bit đánh dấu một trường đã được dùng."""
        empty_labels = ("", "", "")
        field_mask_count = 1 << len(self.FIELDS)
        best_from = [
            [(0, empty_labels) for _ in range(field_mask_count)]
            for _ in range(len(candidates) + 1)
        ]
        for position in range(len(candidates) - 1, -1, -1):
            options = candidates[position]
            if anchors is not None:
                options = [
                    (
                        end,
                        field,
                        label,
                        score * (len(self.FIELDS) + 1)
                        + int(
                            not anchors[field]
                            and self._supported_by_geography(field, label, anchors)
                        ),
                    )
                    for end, field, label, score in options
                ]
            if randomize:
                options = sorted(options)

            for used_fields in range(field_mask_count):
                best_score, best_labels = best_from[position + 1][used_fields]
                tied_options = 1
                for end, field, label, score in options:
                    field_bit = 1 << field
                    if used_fields & field_bit:
                        continue
                    next_score, next_labels = best_from[end][used_fields | field_bit]
                    total_score = score + next_score
                    if total_score < best_score:
                        continue
                    labels = next_labels[:field] + (label,) + next_labels[field + 1 :]
                    if total_score > best_score:
                        best_score, best_labels = total_score, labels
                        tied_options = 1
                    elif randomize:
                        tied_options += 1
                        if self._rng.randrange(tied_options) == 0:
                            best_labels = labels
                    else:
                        best_labels = tuple(
                            old if old == new else ""
                            for old, new in zip(best_labels, labels)
                        )
                best_from[position][used_fields] = best_score, best_labels
        score, labels = best_from[0][0]
        return (score, labels) if with_score else labels

    def _supported_by_geography(self, field, label, anchors):
        local_names = [
            (other, name)
            for other, name in enumerate(anchors)
            if other != field and name
        ]
        return bool(local_names) and any(
            all(link[other] == name for other, name in local_names)
            for link in self._links_by_field[field].get(label, ())
        )

    def _abbreviation_candidates(self, text):
        text = self.CITY_INITIALS.sub("tp ", text)
        token_prefix = "zzabb"
        while token_prefix in text.casefold():
            token_prefix += "z"
        marked = {}

        def mark(match):
            dotted = match.group("dotted")
            raw = dotted or match.group("compact")
            if dotted is None:
                if not raw.isupper():
                    return match.group()
                if (raw.casefold(),) in self._separate_markers:
                    remainder = text[match.end() :]
                    if self.SEPARATORS.split(remainder, maxsplit=1)[0].strip():
                        return match.group()
            text_has_dots = "." in raw
            letters = self._strip_diacritics(raw.casefold().replace(".", ""))
            suffix = letters[1:]
            marker = self._field_by_marker.get((letters[0],))
            variants = set(self._names_by_initials.get(letters, ()))
            variants.update(self._common_aliases.get(letters, ()))
            alternate = {
                (field, name)
                for field, name in self._names_by_initials.get(suffix, ())
                if marker == field and len(suffix) >= 2 and text_has_dots
            }
            if match.group("province"):
                variants = {(field, name) for field, name in variants if field == 2}
                alternate = set()
            ambiguous_fields = {
                field
                for field, label in variants
                if any(
                    other == field and candidate != label
                    for other, candidate in alternate
                )
            }
            options = variants | alternate
            if not options:
                return match.group()
            if dotted is None and tuple(self._tokenize(raw)) in self._exact_names:
                return match.group()
            token = f"{token_prefix}{len(marked)}"
            marked[token] = (options, ambiguous_fields)
            return f" {token} "

        text = self.INITIAL_RUN.sub(mark, text)
        if not marked:
            return None
        words, ends = self._split_address(text)
        candidates = self._find_candidates(words, ends)
        anchors = self._select_segmentation(candidates)
        initials = set()
        ambiguous = set()
        start = 0
        for end in ends:
            for index in range(start, end):
                if words[index] not in marked:
                    continue
                options, ambiguous_fields = marked[words[index]]
                marker_start = index
                field_hint = None
                for length in (2, 1):
                    if index - length >= start:
                        field_hint = self._field_by_marker.get(
                            tuple(words[index - length : index])
                        )
                        if field_hint is not None:
                            marker_start = index - length
                            break
                referenced_fields = {
                    field
                    for field, label in options
                    if self._links_by_field[field].get(label)
                }
                for field, label in options:
                    if (field_hint is None or field == field_hint) and not anchors[
                        field
                    ]:
                        initials.add((field, label))
                        if field in ambiguous_fields and field in referenced_fields:
                            ambiguous.add((field, label))
                        candidates[marker_start].append((index + 1, field, label, 21))
            start = end
        return candidates, anchors, initials, ambiguous

    def _resolve_abbreviations_with_context(self, text):
        extracted = self._abbreviation_candidates(text)
        if extracted is None:
            return None
        candidates, anchors, initials, ambiguous = extracted
        links = set()
        for field, label in initials:
            links.update(self._links_by_field[field].get(label, ()))

        best = None
        choices = set()
        for link in links:
            if any(name and name != link[field] for field, name in enumerate(anchors)):
                continue
            allowed = [
                [item for item in choices if item[2] == link[item[1]]]
                for choices in candidates
            ]
            score, labels = self._select_segmentation(allowed, with_score=True)
            if any(
                name and labels[field] != name for field, name in enumerate(anchors)
            ):
                continue
            count = sum(bool(label) for label in labels)
            if count < 2 or not any(
                (field, label) in initials for field, label in enumerate(labels)
            ):
                continue
            rank = (count, score)
            if best is None or rank > best:
                best, choices = rank, {labels}
            elif rank == best:
                choices.add(labels)
        if choices:
            return self._rng.choice(sorted(choices))
        if ambiguous and any(anchors):
            result = self._select_segmentation(candidates, randomize=True)
            if any((field, name) in ambiguous for field, name in enumerate(result)):
                return result
        return None

    def _resolve_deletions_with_context(self, text):
        parts = self.SEPARATORS.split(self.CITY_INITIALS.sub("tp ", text))
        if len(parts) < 2:
            return None
        components = {}
        for part in parts:
            for words in self._remove_other_levels(self._tokenize(part)):
                if len(words) < 2:
                    continue
                offset = int(bool(self.HOUSE_NUMBER.fullmatch(words[0])))
                for start, first, field, allowed in self._find_field_markers(
                    words, offset, len(words)
                ):
                    if not allowed:
                        continue
                    span = tuple(words[start:])
                    if first is not None:
                        span = (first, *span[1:])
                    components.setdefault(field, []).append(span)
                    break
        if sum(len(spans) == 1 for spans in components.values()) < 2:
            return None

        base = {}
        weak = {}
        empty = ("", "", "")
        for field, spans in components.items():
            if len(spans) != 1:
                continue
            span = spans[0]
            matches = dict(
                self._name_matches(span, field, True, True, fuzzy=True, extra_edit=True)
            )
            exact = {
                name: score
                for (_, name), score in matches.items()
                if score >= self.JOINED_NAME_SCORE
            }
            if exact:
                best = max(exact.values())
                base[field] = {
                    name: score for name, score in exact.items() if score == best
                }
                continue
            options = {name: score for (_, name), score in matches.items()}
            for _, label, score in self._deletion_matches(span, field, empty):
                options[label] = max(score, options.get(label, 0))
            if options:
                weak[field] = options
        if not weak:
            return None

        links = set()
        for field, names in weak.items():
            for name in names:
                links.update(self._links_by_field[field].get(name, ()))

        top = None
        outputs = set()
        for link in links:
            if any(link[field] not in names for field, names in base.items()):
                continue
            confirmed = [
                (field, options[link[field]])
                for field, options in weak.items()
                if link[field] in options
            ]
            if not confirmed or len(base) + len(confirmed) < 2:
                continue
            if len(confirmed) != len(weak):
                continue
            represented = set(base) | {field for field, _ in confirmed}
            rank = (len(represented), sum(score for _, score in confirmed))
            labels = tuple(
                link[field] if field in represented else ""
                for field in range(len(self.FIELDS))
            )
            if top is None or rank > top:
                top, outputs = rank, {labels}
            elif rank == top:
                outputs.add(labels)
        if not outputs and (1 in weak or 2 in weak):
            pair_score = None
            wards = base.get(1) or weak.get(1) or {}
            provinces = base.get(2) or weak.get(2) or {}
            for ward, ward_score in wards.items():
                for province in self._provinces_by_ward.get(ward, ()):
                    if province not in provinces:
                        continue
                    score = ward_score + provinces[province]
                    labels = ("", ward, province)
                    if pair_score is None or score > pair_score:
                        pair_score, outputs = score, {labels}
                    elif score == pair_score:
                        outputs.add(labels)
        return self._rng.choice(sorted(outputs)) if outputs else None


if __name__ == "__main__":
    # Download public test
    PUBLIC_FILES = {
        "public.json": "18qzaHmx9-fcKPi4gTq304G2JvXy_g6XW",
        "public_list_province.txt": "1PHRkRLRaO2vFivLbcPJsaxjvZ7K_I3lU",
        "public_list_ward.txt": "1QrSouYn6IUEW7Impje1vOxzsksjlAJ-h",
        "public_list_street.txt": "1yP2dBE8K9QtUiaLPewtQRr-hDH0gOgfa",
    }

    for filename, file_id in PUBLIC_FILES.items():
        if not Path(filename).is_file():
            import gdown

            gdown.download(id=file_id, output=filename, quiet=False)
            if not Path(filename).is_file():
                raise FileNotFoundError(f"Cannot download scoring data: {filename}")

    def _judge_normalize(s: str, context=None):
        return s

    EXCEL_FILE = f'{TEAM_NAME}.xlsx'

    import json
    import time
    with open('public.json', encoding='utf-8') as f:
        data = json.load(f)

    with open("public_list_province.txt", encoding="utf-8") as f:
        list_province = f.read().strip().splitlines()

    with open("public_list_ward.txt", encoding="utf-8") as f:
        list_ward = f.read().strip().splitlines()

    with open("public_list_street.txt", encoding="utf-8") as f:
        list_street = f.read().strip().splitlines()

    summary_only = True
    df = []
    solution = Solution(
        list_province=list_province,
        list_ward=list_ward,
        list_street=list_street,
    )
    timer = []
    correct = 0
    for test_idx, data_point in enumerate(data):
        address = data_point["address"]

        ok = 0
        try:
            answer = data_point["result"].copy()
            answer["province_normalized"] = _judge_normalize(answer["province"])
            answer["ward_normalized"] = _judge_normalize(answer["ward"])
            answer["street_normalized"] = _judge_normalize(answer["street"])

            start = time.perf_counter_ns()
            result = solution.process(address)
            finish = time.perf_counter_ns()
            timer.append(finish - start)
            result["province_normalized"] = _judge_normalize(result["province"])
            result["ward_normalized"] = _judge_normalize(result["ward"])
            result["street_normalized"] = _judge_normalize(result["street"])

            province_correct = int(answer["province_normalized"] == result["province_normalized"])
            ward_correct = int(answer["ward_normalized"] == result["ward_normalized"])
            street_correct = int(answer["street_normalized"] == result["street_normalized"])
            ok = province_correct + street_correct + ward_correct

            df.append([
                test_idx,
                address,

                answer["province"],
                result["province"],
                answer["province_normalized"],
                result["province_normalized"],
                province_correct,

                answer["ward"],
                result["ward"],
                answer["ward_normalized"],
                result["ward_normalized"],
                ward_correct,

                answer["street"],
                result["street"],
                answer["street_normalized"],
                result["street_normalized"],
                street_correct,

                ok,
                timer[-1] / 1_000_000_000,
            ])
        except Exception as e:
            print(f"{answer = }")
            print(f"{result = }")
            df.append([
                test_idx,
                address,

                answer["province"],
                "EXCEPTION",
                answer["province_normalized"],
                "EXCEPTION",
                0,

                answer["ward"],
                "EXCEPTION",
                answer["ward_normalized"],
                "EXCEPTION",
                0,

                answer["street"],
                "EXCEPTION",
                answer["street_normalized"],
                "EXCEPTION",
                0,

                0,
                0,
            ])
            # any failure count as a zero correct
            pass
        correct += ok


        if not summary_only:
            # responsive stuff
            print(f"Test {test_idx:5d}/{len(data):5d}")
            print(f"Correct: {ok}/3")
            print(f"Time Executed: {timer[-1] / 1_000_000_000:.4f}")


    print(f"-"*30)
    total = len(data) * 3
    score_scale_10 = round(correct / total * 10, 2)
    if len(timer) == 0:
        timer = [0]
    max_time_sec = round(max(timer) / 1_000_000_000, 4)
    avg_time_sec = round((sum(timer) / len(timer)) / 1_000_000_000, 4)

    import pandas as pd

    df2 = pd.DataFrame(
        [[correct, total, score_scale_10, max_time_sec, avg_time_sec]],
        columns=['correct', 'total', 'score / 10', 'max_time_sec', 'avg_time_sec',],
    )

    columns = [
        'ID',
        'text',

        'province',
        'province_student',
        'province_normalized',
        'province_student_normalized',
        'province_correct',

        'ward',
        'ward_student',
        'ward_normalized',
        'ward_student_normalized',
        'ward_correct',

        'street',
        'street_student',
        'street_normalized',
        'street_student_normalized',
        'street_correct',

        'total_correct',
        'time_sec',
    ]

    df = pd.DataFrame(df)
    df.columns = columns

    print(f'{TEAM_NAME = }')
    print(f'{EXCEL_FILE = }')
    print(df2)

    writer = pd.ExcelWriter(EXCEL_FILE, engine='xlsxwriter')
    df2.to_excel(writer, index=False, sheet_name='summary')
    df.to_excel(writer, index=False, sheet_name='details')
    writer.close()
