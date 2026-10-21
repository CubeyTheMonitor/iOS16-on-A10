"""Explicit selection for the inherited A40 tooling; no inferred A10 map."""


def require_supported_board(board):
    if board != 'a40':
        raise ValueError(
            f'{board or "unspecified"}: no validated loader/kernel hardware profile; '
            'A10 RAM, framebuffer handover and storage state must be measured. '
            'Only --board a40 selects the inherited A40 implementation.')
