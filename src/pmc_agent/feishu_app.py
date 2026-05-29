from __future__ import annotations

from pmc_agent.env import load_env_file
from pmc_agent.external_integrations.feishu import create_default_feishu_bot


def main() -> None:
    load_env_file(override=False)
    create_default_feishu_bot().run_forever()


if __name__ == "__main__":
    main()
