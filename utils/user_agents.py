from typing import NamedTuple


class UAProfile(NamedTuple):
    label: str
    user_agent: str
    is_mobile: bool
    viewport_width: int
    viewport_height: int


PROFILES: dict[str, UAProfile] = {
    "desktop_chrome": UAProfile(
        label="Desktop Chrome (по умолчанию)",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        is_mobile=False,
        viewport_width=1920,
        viewport_height=1080,
    ),
    "mobile_chrome": UAProfile(
        label="Mobile Chrome (Android)",
        user_agent=(
            "Mozilla/5.0 (Linux; Android 14; Pixel 8) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.6367.82 Mobile Safari/537.36"
        ),
        is_mobile=True,
        viewport_width=375,
        viewport_height=812,
    ),
    "mobile_safari": UAProfile(
        label="Mobile Safari (iPhone)",
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.4.1 Mobile/15E148 Safari/604.1"
        ),
        is_mobile=True,
        viewport_width=375,
        viewport_height=812,
    ),
    "custom": UAProfile(
        label="Custom",
        user_agent="",
        is_mobile=False,
        viewport_width=1920,
        viewport_height=1080,
    ),
}


def get_profile(preset: str, custom_ua: str = "") -> UAProfile:
    profile = PROFILES.get(preset, PROFILES["desktop_chrome"])
    if preset == "custom" and custom_ua:
        return profile._replace(user_agent=custom_ua)
    return profile
