import json

import pytest

from app.database.repository import PlatformRepository, ProductRepository
from app.services.wishlist import WishlistService
from app.utils.url_parser import extract_platform_from_url


class TestUrlParser:
    def test_extract_platform_from_myntra_url(self):
        platform = extract_platform_from_url("https://www.myntra.com/p/abc")
        assert platform == "myntra"

    def test_extract_platform_from_unknown_url(self):
        platform = extract_platform_from_url("https://example.com/product/123")
        assert platform is None


class TestWishlistService:
    @pytest.fixture
    def platform(self, test_session):
        return PlatformRepository.create(
            test_session,
            name="myntra",
            display_name="Myntra",
            base_url="https://www.myntra.com",
        )

    def test_add_from_url_creates_wishlist_item(self, test_session, platform):
        wishlist = WishlistService.add_from_url(
            test_session,
            url="https://www.myntra.com/p/abc",
            brand="Nike",
            model_name="Air Max 90",
            title="Nike Air Max 90",
            platforms_to_track=["myntra", "ajio"],
            size_scope=["11", "11.5", "12", "12.5"],
        )

        assert wishlist.platform == "myntra"
        assert wishlist.brand == "Nike"
        assert wishlist.model_name == "Air Max 90"
        assert wishlist.normalized_name == "nike air max 90"
        assert json.loads(wishlist.size_scope) == ["11", "11.5", "12", "12.5"]
        assert json.loads(wishlist.platforms_to_track) == ["myntra", "ajio"]
        assert wishlist.is_active is True

    def test_find_exact_matches(self, test_session, platform):
        ProductRepository.create_or_update(
            test_session,
            platform_id=platform.id,
            product_url="https://www.myntra.com/p/abc",
            platform_product_id="abc",
            brand="Nike",
            model_name="Air Max 90",
            title="Nike Air Max 90",
            listed_price=9000.0,
            discounted_price=8500.0,
            in_stock=True,
            sizes_available='["11", "12"]',
        )

        wishlist = WishlistService.add_from_url(
            test_session,
            url="https://www.myntra.com/p/abc",
            brand="Nike",
            model_name="Air Max 90",
            title="Nike Air Max 90",
            platforms_to_track=["myntra"],
            size_scope=["11", "12"],
        )

        matches = WishlistService.find_exact_matches(test_session, wishlist)

        assert len(matches) == 1
        assert matches[0].brand == "Nike"
        assert matches[0].model_name == "Air Max 90"

    def test_list_all_and_toggle_active_state(self, test_session, platform):
        WishlistService.add_from_url(
            test_session,
            url="https://www.myntra.com/p/abc",
            brand="Nike",
            model_name="Air Max 90",
            title="Nike Air Max 90",
            platforms_to_track=["myntra"],
            size_scope=["11"],
        )

        entries = WishlistService.get_all(test_session)
        assert len(entries) == 1
        assert entries[0].is_active is True

        updated = WishlistService.set_active(test_session, "https://www.myntra.com/p/abc", False)
        assert updated is not None
        assert updated.is_active is False

        all_entries = WishlistService.get_all(test_session)
        assert all_entries[0].is_active is False

    def test_delete_removes_wishlist_entry(self, test_session, platform):
        WishlistService.add_from_url(
            test_session,
            url="https://www.myntra.com/p/abc",
            brand="Nike",
            model_name="Air Max 90",
            title="Nike Air Max 90",
            platforms_to_track=["myntra"],
            size_scope=["11"],
        )

        deleted = WishlistService.delete(test_session, "https://www.myntra.com/p/abc")
        assert deleted is True

        remaining = WishlistService.get_all(test_session)
        assert remaining == []
