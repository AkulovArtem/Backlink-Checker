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
            "Chrome/147.0.0.0 Safari/537.36"
        ),
        is_mobile=False,
        viewport_width=1920,
        viewport_height=1080,
    ),
    "mobile_chrome": UAProfile(
        label="Mobile Chrome (Android)",
        user_agent=(
            "Mozilla/5.0 (Linux; Android 15; Pixel 9) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/147.0.7683.64 Mobile Safari/537.36"
        ),
        is_mobile=True,
        viewport_width=393,
        viewport_height=852,
    ),
    "mobile_safari": UAProfile(
        label="Mobile Safari (iPhone)",
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 26_4_2 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/26.4.2 Mobile/15E148 Safari/604.1"
        ),
        is_mobile=True,
        viewport_width=393,
        viewport_height=852,
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
