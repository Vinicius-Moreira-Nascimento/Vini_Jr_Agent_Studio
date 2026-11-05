import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_DIR = ROOT / "tests"

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main():
    print("=" * 60)
    print(" VINI_JR AGENT STUDIO - TEST RUNNER")
    print("=" * 60)

    if not TEST_DIR.is_dir():
        print("Diret?rio tests n?o encontrado.")
        return 2

    suite = unittest.defaultTestLoader.discover(
        start_dir=str(TEST_DIR),
        pattern="test_*.py",
        top_level_dir=str(ROOT),
    )

    result = unittest.TextTestRunner(
        verbosity=2
    ).run(suite)

    print("\n" + "=" * 60)
    print(" RESUMO DOS TESTES")
    print("=" * 60)
    print(f"Executados: {result.testsRun}")
    print(f"Falhas: {len(result.failures)}")
    print(f"Erros: {len(result.errors)}")
    print(f"Sucessos: {result.testsRun - len(result.failures) - len(result.errors)}")

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
