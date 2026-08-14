from typer.testing import CliRunner

import tempest
from tempest.cli.main import app

runner = CliRunner()


def test_version_command_reports_the_package_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert tempest.__version__ in result.output
