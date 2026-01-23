from pathlib import Path


def main() -> None:
    from streamlit.web import bootstrap

    app_path = Path(__file__).resolve().parent / "streamlit_app.py"
    bootstrap.run(
        str(app_path),
        "",
        [],
        flag_options={
            "server.headless": True,
            "browser.gatherUsageStats": False,
        },
    )


if __name__ == "__main__":
    main()
