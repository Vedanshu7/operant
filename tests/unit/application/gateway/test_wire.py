import operant.application.gateway.wire as wire
import operant.domain.models.actions as actions
import operant.domain.models.digest as digest

DIGEST = digest.ScreenDigest(
    app="Chrome",
    window_title="ParaBank | Welcome",
    text="Customer Login Username Password",
    controls=(
        digest.Control(
            ref="c0",
            role="text_field",
            name="",
            label="Username",
            path="content>input:0",
            box=digest.Box(0.1, 0.2, 0.3, 0.05),
        ),
        digest.Control(
            ref="c1",
            role="button",
            name="Log In",
            label="Password",
            path="content>button:0",
            box=digest.Box(0.1, 0.3, 0.2, 0.05),
        ),
    ),
)


def test_wire_digest_round_trip():
    assert wire.digest_from_dict(wire.digest_to_dict(DIGEST)) == DIGEST


def test_wire_action_round_trip_keeps_sensitivity_tags():
    action = actions.SurfaceAction(
        kind="fill",
        ref="c0",
        value="john",
        target_text="Username",
        data_class="credential",
        export_from="parabank",
        secret_ref="username",
        step="edge-3",
    )
    again = wire.action_from_dict(wire.action_to_dict(action))
    assert again == action
    assert (
        again.data_class,
        again.export_from,
        again.secret_ref,
        again.step,
    ) == ("credential", "parabank", "username", "edge-3")
