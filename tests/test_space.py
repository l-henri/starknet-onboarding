from typing import List, NamedTuple, Tuple
import pytest

from starkware.starknet.business_logic.state.state import BlockInfo
from starkware.starknet.testing.starknet import Starknet
from starkware.starknet.testing.contract import StarknetContract
from starkware.starknet.public.abi import get_selector_from_name

from fixtures import *
from deploy import deploy_contract
from utils import assert_revert, str_to_felt, to_uint

ADMIN = get_selector_from_name('admin')
ANYONE = get_selector_from_name('anyone')
SPACE_SIZE = 6
MAX_FELT = 2**251 + 17 * 2**192 + 1

@pytest.fixture
async def space_factory(starknet: Starknet) -> StarknetContract:
    rand = await deploy_contract(starknet, 'test/fake_rand.cairo')
    space = await deploy_contract(starknet, 'core/space.cairo', constructor_calldata=[ADMIN])
    dust = await deploy_contract(starknet, 'core/dust.cairo', constructor_calldata=[space.contract_address, rand.contract_address])
    await space.initialize(dust.contract_address, SPACE_SIZE).invoke(caller_address=ADMIN)
    return space, dust

@pytest.mark.asyncio
async def test_next_turn_only_owner(space_factory):
    space, _ = space_factory
    await assert_revert(space.next_turn().invoke(caller_address=ANYONE), reverted_with='Ownable: caller is not the owner')

@pytest.mark.asyncio
async def test_next_turn_no_ship(space_factory):
    space, dust = space_factory

    # Assert grid is empty
    await assert_grid_dust(space, [])

    # Next turn --------------------------------------------------
    await space.next_turn().invoke(caller_address=ADMIN)

    await assert_dust_position(dust, 1, Vector2(0, 1), Vector2(0, 1))
    await assert_grid_dust(space, [Dust(Vector2(0, 1), 1)])

    # Next turn --------------------------------------------------
    await space.next_turn().invoke(caller_address=ADMIN)

    await assert_dust_position(dust, 1, Vector2(0, 2), Vector2(0, 1))
    await assert_dust_position(dust, 2, Vector2(0, 4), Vector2(0, -1))
    await assert_grid_dust(space, [Dust(Vector2(0, 2), 1), Dust(Vector2(0, 4), 2)])

    # Next turn --------------------------------------------------
    await space.next_turn().invoke(caller_address=ADMIN)

    await assert_dust_position(dust, 1, Vector2(0, 3), Vector2(0, 1))
    await assert_dust_position(dust, 2, Vector2(0, 3), Vector2(0, -1))
    await assert_dust_position(dust, 3, Vector2(5, 1), Vector2(0, 1))

    # A collision occured, assert the dust was burnt
    await assert_revert(dust.ownerOf(to_uint(1)).call(), reverted_with='ERC721: owner query for nonexistent token')

    await assert_grid_dust(space, [Dust(Vector2(0, 3), 1), Dust(Vector2(5, 1), 3)])


#
# Helpers to assert the state of the entire grid
#
class Vector2(NamedTuple):
    x: int
    y: int

class Dust(NamedTuple):
    pos: Vector2
    id: int

async def assert_grid_dust(space, dusts:List[Dust]):
    for x in range(SPACE_SIZE):
        for y in range(SPACE_SIZE):
            expected_id = get_expected_dust_id_at(Vector2(x, y), dusts)
            execution_info = await space.get_dust_at(x, y).call()
            res = execution_info.result
            assert res == (to_uint(expected_id),), 'Expected dust {id}, at position ({x}, {y}). Got {res}'.format(id=expected_id, x=x, y=y, res=res)

def get_expected_dust_id_at(position:Vector2, dusts:List[Dust]):
    for d in dusts:
        if d.pos.x == position.x and d.pos.y == position.y:
            return d.id
    return 0

async def assert_dust_position(dust, id:int, position:Vector2, direction:Vector2):
    execution_info = await dust.metadata(to_uint(id-1)).call()
    _, (px, py), (dx, dy) = execution_info.result.metadata
    assert px == position.x
    assert py == position.y
    assert dx == direction.x % MAX_FELT
    assert dy == direction.y % MAX_FELT