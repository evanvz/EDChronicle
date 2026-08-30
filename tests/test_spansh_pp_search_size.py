"""search_pp_systems() requests more results from Spansh for missions
without a server-side power filter (undermining/acquisition/all) --
otherwise the distance-sorted page can be entirely consumed by the
searcher's own dense home territory before ever reaching a relevant
candidate a bit farther out (confirmed live: 0 undermining results
within 100 ly of a Stronghold system, even though the closest actual
rival-controlled system was only 22.6 ly away)."""
from unittest.mock import patch

from edc.core.spansh_client import SpanshClient


def _empty_response():
    class _Resp:
        def raise_for_status(self):
            pass
        def json(self):
            return {"results": []}
    return _Resp()


def _requested_size(mission: str) -> int:
    client = SpanshClient()
    with patch("edc.core.spansh_client.requests.post", return_value=_empty_response()) as mock_post:
        client.search_pp_systems(
            power="Aisling Duval", mission=mission,
            ref_x=0.0, ref_y=0.0, ref_z=0.0,
        )
    return mock_post.call_args.kwargs["json"]["size"]


def test_reinforcement_keeps_small_default_size():
    # Server-side controlling_power filter already excludes everything
    # irrelevant, so the size cap never truncates away a real candidate.
    assert _requested_size("reinforcement") == 50


def test_undermining_requests_a_larger_default_size():
    assert _requested_size("undermining") == 250


def test_acquisition_requests_a_larger_default_size():
    assert _requested_size("acquisition") == 250


def test_all_requests_a_larger_default_size():
    assert _requested_size("all") == 250


def test_explicit_size_overrides_the_mission_default():
    client = SpanshClient()
    with patch("edc.core.spansh_client.requests.post", return_value=_empty_response()) as mock_post:
        client.search_pp_systems(
            power="Aisling Duval", mission="undermining",
            ref_x=0.0, ref_y=0.0, ref_z=0.0, size=10,
        )
    assert mock_post.call_args.kwargs["json"]["size"] == 10
