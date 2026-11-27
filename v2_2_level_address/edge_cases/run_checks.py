import argparse
import ast
import json
import random
import unicodedata
from pathlib import Path

CASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = CASE_DIR.parent
FIELDS = ("street", "ward", "province")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_solution(address_links=(), *, random_seed=2026):
    notebook_path = PROJECT_DIR / "Group_01" / "Group_01.ipynb"
    notebook = read_json(notebook_path)
    namespace = {}
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        try:
            tree = ast.parse("".join(cell["source"]))
        except SyntaxError:
            # Các cell chứa magic hoặc lệnh shell của Jupyter không cần cho Solution.
            continue
        imports_and_solution = [
            node for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
            or isinstance(node, ast.ClassDef) and node.name == "Solution"
        ]
        selected = ast.Module(body=imports_and_solution, type_ignores=[])
        exec(compile(selected, str(notebook_path), "exec"), namespace)
        if "Solution" in namespace:
            break
    dictionaries = {
        f"list_{field}": (PROJECT_DIR / f"public_list_{field}.txt")
        .read_text(encoding="utf-8-sig").strip().splitlines()
        for field in FIELDS
    }
    return namespace["Solution"](**dictionaries, address_links=address_links, random_seed=random_seed)


def without_accents(text):
    text = unicodedata.normalize("NFD", text.casefold().replace("đ", "d"))
    return "".join(char for char in text if not unicodedata.combining(char))


def remove_middle_letter(text):
    positions = [i for i, char in enumerate(text) if char.isalpha()]
    if len(positions) < 4:
        return text
    index = positions[len(positions) // 2]
    return text[:index] + text[index + 1:]


def swap_adjacent_letters(text):
    positions = [
        i for i in range(len(text) - 1) if text[i:i + 2].isalpha() and text[i] != text[i + 1]
    ]
    if not positions:
        return text
    index = positions[len(positions) // 2]
    return text[:index] + text[index + 1] + text[index] + text[index + 2:]


def generate_variants(rows):
    groups = {}

    def add(group, address, expected):
        groups.setdefault(group, []).append((address, expected))

    for row in rows:
        address, expected = row["address"], row["result"]
        street, ward, province = (expected[field] for field in FIELDS)
        parts = [part.strip() for part in address.split(",")]
        if len(parts) != len(FIELDS):
            raise ValueError(f"Ca public cần ba phần để sinh biến thể: {address!r}")
        add("Public gốc", address, expected)
        add("Xuống dòng + đảo thứ tự + Unicode NFD",
            unicodedata.normalize("NFD", "\n".join(parts[i] for i in (1, 2, 0))), expected)
        add("Đảo thứ tự + bỏ dấu tiếng Việt + bỏ dấu phẩy",
            " ".join(without_accents(parts[i]) for i in (2, 0, 1)), expected)

        for index, part in enumerate(parts):
            remaining = {field: expected[field] if i == index else "" for i, field in enumerate(FIELDS)}
            add("Thiếu hai trường", part, remaining)

        for transform, name in (
            (remove_middle_letter, "Mất một ký tự trên đường"),
            (swap_adjacent_letters, "Đảo hai ký tự trên đường"),
        ):
            altered = transform(street)
            if altered != street:
                add(name, f"TP. {province}, Đ. {altered}, P. {ward}", expected)
                add(f"{name} + bỏ dấu phẩy", f"{province} {altered} {ward}", expected)

        words = street.split()
        if len(words) >= 3:
            middle = len(words) // 2
            shortened = " ".join(words[:middle] + words[middle + 1:])
            add("Thiếu từ giữa tên đường", f"Đường {shortened}, P.{ward}, TP.{province}", expected)
        if len(words) >= 2 and all(word.isalpha() for word in words):
            initials = ".".join(word[0] for word in words)
            add("Viết tắt chữ đầu tên đường", f"TP.{province}, P.{ward}, Đ.{initials}", expected)

        folded = without_accents(street)
        if len(folded.replace(" ", "")) >= 11 and all(word.isalpha() for word in words):
            chars = list(folded)
            positions = [i for i, char in enumerate(chars) if char.isalpha()]
            for index in (positions[2], positions[-3]):
                chars[index] = "x" if chars[index] != "x" else "q"
            add("Sai hai ký tự + đảo thứ tự + bỏ dấu tiếng Việt",
                f"tp {without_accents(province)}, d {''.join(chars)}, p {without_accents(ward)}",
                expected)
    return groups


def evaluate(solution, group, examples, failure_limit):
    fields_correct = addresses_correct = 0
    failures = []
    for address, expected in examples:
        actual = solution.process(address)
        alternatives = expected if isinstance(expected, list) else [expected]
        correct = max(sum(actual[field] == option[field] for field in FIELDS)
                      for option in alternatives)
        fields_correct += correct
        addresses_correct += correct == len(FIELDS)
        if correct != len(FIELDS):
            failures.append((address, expected, actual))

    print(f"{group} | địa chỉ {addresses_correct}/{len(examples)}"
          f" | trường {fields_correct}/{len(FIELDS) * len(examples)}")
    for address, expected, actual in failures[:failure_limit]:
        print(f"  {address!r}\n  Mong đợi: {expected}\n  Thực tế:  {actual}")
    return not failures


def check_joint_cases(solution_type, failure_limit):
    fixture = read_json(CASE_DIR / "joint_cases.json")
    failures = []
    for case in fixture["cases"]:
        solution = solution_type(**fixture["dictionaries"], address_links=case["links"], random_seed=2026)
        expected = case["expected"]
        if isinstance(expected, list):
            results = [solution.process(case["address"]) for _ in range(32)]
            if not all(result in expected for result in results) or not all(option in results for option in expected):
                failures.append((case, results))
        else:
            actual = solution.process(case["address"])
            if actual != expected:
                failures.append((case, actual))
    total = len(fixture["cases"])
    print(f"Ca kiểm tra xếp hạng chung | địa chỉ {total - len(failures)}/{total}")
    for case, actual in failures[:failure_limit]:
        print(f"  {case['name']}\n  Mong đợi: {case['expected']}\n  Thực tế:  {actual}")
    return not failures


def check_heavy_deletion(solution_type, failure_limit):
    fixture = read_json(CASE_DIR / "heavy_deletion_cases.json")
    solution = solution_type(**fixture["dictionaries"], address_links=fixture["links"], random_seed=2026)
    examples = [(address, dict(zip(FIELDS, expected))) for address, expected in fixture["cases"]]
    passed = evaluate(solution, "Ca biên thiếu ký tự", examples, failure_limit)
    tie = fixture["tie"]
    names = {solution.process(tie["address"])["street"] for _ in range(40)}
    tie_passed = names == set(tie["expected_streets"])
    print(f"Bốc thăm trong các tên hợp lệ: {', '.join(sorted(names))}")
    return passed and tie_passed


def evaluate_60_percent_deletions():
    rows = read_json(PROJECT_DIR / "public.json")
    markers = ("Đường", "P.", "TP.")
    for damaged_field in (*FIELDS, "all"):
        # Cùng seed cho mỗi nhóm để tiện chạy lại.
        rng = random.Random(72)
        solver = load_solution()
        examples = []
        for row in rows:
            expected = row["result"]
            parts = []
            for field, marker in zip(FIELDS, markers):
                name = unicodedata.normalize("NFC", expected[field])
                if damaged_field in (field, "all"):
                    letters = [index for index, char in enumerate(name) if char.isalpha()]
                    removed = set(rng.sample(letters, len(letters) * 60 // 100))
                    name = "".join(char for index, char in enumerate(name) if index not in removed)
                    name = " ".join(name.split())
                parts.append(f"{marker} {name}")
            examples.append((", ".join(parts), expected))
        label = "Cả ba trường" if damaged_field == "all" else damaged_field
        evaluate(solver, f"Xóa tối đa 60% · {label}", examples, 0)


def main():
    parser = argparse.ArgumentParser(description="Đánh giá Group_01.ipynb trên các edge case.")
    parser.add_argument("--manual-only", action="store_true", help="Chỉ chạy các ca viết tay.")
    parser.add_argument("--requirements", action="store_true", help="Chạy các ca theo xác nhận đề bài.")
    parser.add_argument("--show-failures", type=int, default=2, metavar="N",
                        help="Số ví dụ sai tối đa cho mỗi nhóm, mặc định 2.")
    parser.add_argument("--context", action="store_true", help="Chạy ca kiểm thử có bảng quan hệ.")
    parser.add_argument("--heavy-deletion", action="store_true", help="Kiểm tra ca biên thiếu tới 60% ký tự.")
    parser.add_argument("--deletion-benchmark", action="store_true",
                        help="Sinh địa chỉ bị xóa tối đa 60% ký tự từ tập public.")
    args = parser.parse_args()
    if args.requirements:
        cases = read_json(CASE_DIR / "requirements_cases.json")
        solver = load_solution()
        passed = evaluate(solver, "Ca theo yêu cầu đề", [
            (case["address"], case["expected"]) for case in cases
        ], max(args.show_failures, 0))
        if not passed:
            raise SystemExit(1)
        return
    if args.deletion_benchmark:
        evaluate_60_percent_deletions()
        return
    if args.heavy_deletion:
        if not check_heavy_deletion(type(load_solution()), max(args.show_failures, 0)):
            raise SystemExit(1)
        return
    if args.context:
        fixture = read_json(CASE_DIR / "context_cases.json")
        solution = load_solution(fixture["links"])
        cases = fixture["cases"]
        failure_limit = max(args.show_failures, 0)
        passed = evaluate(solution, "Ca có ngữ cảnh địa lý",
                          [(c["address"], c["expected"]) for c in cases], failure_limit)
        joint_passed = check_joint_cases(type(solution), failure_limit)
        if not (passed and joint_passed):
            raise SystemExit(1)
        return
    solution = load_solution()
    manual = read_json(CASE_DIR / "manual_cases.json")
    evaluate(solution, "Ca viết tay", [(c["address"], c["expected"]) for c in manual],
             max(args.show_failures, 0))
    if not args.manual_only:
        groups = generate_variants(read_json(PROJECT_DIR / "public.json"))
        for group, examples in groups.items():
            evaluate(solution, group, examples, max(args.show_failures, 0))


if __name__ == "__main__":
    main()
