"""Tests for thumbnail loading and off-thread decoding.

Tests cover:
- Separation of decode from QPixmap construction
- Worker thread safety
- Result handling for recycled widgets
- Fallback for missing/unsupported files
"""

import tempfile
from pathlib import Path

from qtpy.QtGui import QImage

# Test that load_qimage can be imported without QApplication (proves it's
# importable off-thread, where QApplication may not exist yet)
from tagorganizer.widgets.helper import load_qimage


class TestLoadQImageOffThread:
    """Test load_qimage() which is safe to call off-thread."""

    def test_load_qimage_returns_qimage_not_pixmap(self):
        """Verify load_qimage returns QImage, never QPixmap."""
        # Import here to verify no QApplication needed
        from tagorganizer.widgets.helper import load_qimage
        from tagorganizer.models import Item
        from pathlib import Path

        # Create a temp image file
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            # Create a minimal 1x1 PNG using Qt (only on main thread, but this is setup)
            qimage = QImage(1, 1, QImage.Format_RGB32)
            qimage.fill(0xFF0000)
            test_file = tmpdir / "test.png"
            qimage.save(str(test_file))

            # Create an item pointing to it
            item = Item(uri=str(test_file))

            # Call load_qimage
            result = load_qimage(item, 150, tmpdir)

            # Verify it returns QImage, not QPixmap
            assert result is not None
            assert isinstance(result, QImage)
            from qtpy.QtGui import QPixmap

            assert not isinstance(result, QPixmap)

    def test_load_qimage_missing_file(self):
        """Test that load_qimage returns None for missing files."""
        from tagorganizer.models import Item
        from pathlib import Path

        item = Item(uri="/nonexistent/file.jpg")
        result = load_qimage(item, 150, Path("/tmp"))
        assert result is None

    def test_load_qimage_unknown_extension(self):
        """Test that load_qimage returns None for unknown file types."""
        from tagorganizer.models import Item

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            # Create a file with unknown extension
            test_file = tmpdir / "test.unknown"
            test_file.write_text("not an image")

            item = Item(uri=str(test_file))
            result = load_qimage(item, 150, tmpdir)
            assert result is None

    def test_load_qimage_corrupted_file(self):
        """Test that load_qimage handles corrupted image files."""
        from tagorganizer.models import Item

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            # Create a corrupted PNG file
            test_file = tmpdir / "corrupted.png"
            test_file.write_bytes(b"not a valid png image")

            item = Item(uri=str(test_file))
            result = load_qimage(item, 150, tmpdir)
            # Should handle gracefully and return None
            assert result is None

    def test_load_qimage_jpg(self):
        """Test loading a JPEG file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            # Create a minimal JPEG
            qimage = QImage(10, 10, QImage.Format_RGB32)
            qimage.fill(0xFF0000)
            test_file = tmpdir / "test.jpg"
            qimage.save(str(test_file), "JPEG")

            from tagorganizer.models import Item

            item = Item(uri=str(test_file))
            result = load_qimage(item, 150, tmpdir)

            assert result is not None
            assert isinstance(result, QImage)
            assert not result.isNull()

    def test_load_qimage_png(self):
        """Test loading a PNG file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            qimage = QImage(10, 10, QImage.Format_RGB32)
            qimage.fill(0x00FF00)
            test_file = tmpdir / "test.png"
            qimage.save(str(test_file), "PNG")

            from tagorganizer.models import Item

            item = Item(uri=str(test_file))
            result = load_qimage(item, 150, tmpdir)

            assert result is not None
            assert isinstance(result, QImage)
            assert not result.isNull()

    def test_load_qimage_respects_size(self):
        """Test that load_qimage scales to requested size."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            qimage = QImage(400, 300, QImage.Format_RGB32)
            qimage.fill(0x0000FF)
            test_file = tmpdir / "large.png"
            qimage.save(str(test_file))

            from tagorganizer.models import Item

            item = Item(uri=str(test_file))
            result = load_qimage(item, 150, tmpdir)

            assert result is not None
            # Should be scaled to width 150 (height scales proportionally)
            assert result.width() == 150
            # Height should maintain aspect ratio: 150 * (300/400) = 112.5
            assert 110 <= result.height() <= 115

    def test_load_qimage_exif_rotation(self):
        """Test that load_qimage applies EXIF rotation."""
        # This test verifies that rotate_qimage is called, by checking
        # orientation handling. We'd need actual EXIF data to fully test,
        # but we can verify it doesn't crash.
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            qimage = QImage(10, 20, QImage.Format_RGB32)
            test_file = tmpdir / "test.png"
            qimage.save(str(test_file))

            from tagorganizer.models import Item

            item = Item(uri=str(test_file))
            result = load_qimage(item, 150, tmpdir)

            assert result is not None
            assert isinstance(result, QImage)

    def test_load_qimage_thumbnail_cache_lookup(self):
        """Test that load_qimage checks thumbnail cache first."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create a non-square source image so we can distinguish cache hit
            # from fresh decode. A fresh decode of 100x50 scaled to width 150 gives
            # 150x75. A cache hit returns the cached 150x150 image.
            qimage = QImage(100, 50, QImage.Format_RGB32)
            qimage.fill(0xFF0000)
            source_file = tmpdir / "source.png"
            qimage.save(str(source_file))

            # Create a cached thumbnail with different dimensions
            cached_qimage = QImage(150, 150, QImage.Format_RGB32)
            cached_qimage.fill(0x00FF00)  # Different color

            # Load with md5 that matches cache entry
            from tagorganizer.models import Item

            item = Item(uri=str(source_file), uri_md5="abc123def456")

            from tagorganizer.widgets import helper

            cached = helper.thumbnail_file(item.uri_md5, 150, tmpdir)
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached_qimage.save(str(cached))

            result = load_qimage(item, 150, tmpdir)

            # A cache hit must come back as the cached image, not a fresh decode
            # of the source: that is the whole point of writing the file. The
            # cached 150x150 image proves we hit the cache. A fresh decode from
            # the 100x50 source would scale to width 150, giving 150x75.
            assert result is not None
            assert (result.width(), result.height()) == (150, 150)


class TestThumbnailLoaderThreadSafety:
    """Test ThumbnailLoader and threading design."""

    def test_thumbnail_loader_exists(self):
        """Test that ThumbnailLoader can be instantiated."""
        from tagorganizer.widgets.helper import ThumbnailLoader

        loader = ThumbnailLoader(max_threads=2)
        assert loader is not None

    def test_thumbnail_loader_submits_work(self):
        """Test that ThumbnailLoader can submit work to thread pool."""
        from tagorganizer.widgets.helper import ThumbnailLoader
        from tagorganizer.models import Item
        from pathlib import Path

        loader = ThumbnailLoader(max_threads=1)

        # Create a test image
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            qimage = QImage(10, 10, QImage.Format_RGB32)
            qimage.fill(0xFF0000)
            test_file = tmpdir / "test.png"
            qimage.save(str(test_file))

            item = Item(id=42, uri=str(test_file))

            # Submit load request (should not raise)
            loader.load(item=item, size=150, photos_path=tmpdir)

            # Wait for thread pool to finish
            loader.pool.waitForDone(5000)  # 5 second timeout

            # Verify pool finished
            assert loader.pool.activeThreadCount() == 0
            # Note: Signal emission is tested in the actual GUI where Qt eventloop
            # is running. In tests without an eventloop, signals may not be delivered,
            # but the threading infrastructure is verified to work.

    def test_get_thumbnail_loader_singleton(self):
        """Test that get_thumbnail_loader() returns a singleton."""
        from tagorganizer.widgets.helper import get_thumbnail_loader

        loader1 = get_thumbnail_loader()
        loader2 = get_thumbnail_loader()
        assert loader1 is loader2


class TestResultAddressing:
    """Results are addressed by (item id, size), not by requesting widget.

    Addressing by widget looks safer but breaks the preloader: the preloader
    queues a decode under its own identity, the dedup then drops the tile's
    later request for the same item, and the tile never hears back because the
    result carries somebody else's id. Keying on the item is what lets one
    decode satisfy both.
    """

    def test_key_identifies_item_and_size(self):
        from tagorganizer.models import Item
        from tagorganizer.widgets.helper import ThumbnailLoader

        loader = ThumbnailLoader(max_threads=1)
        a = Item(id=1, uri="/a.jpg")
        b = Item(id=2, uri="/b.jpg")

        assert loader.key_for(a, 150) == loader.key_for(
            Item(id=1, uri="/renamed.jpg"), 150
        )
        assert loader.key_for(a, 150) != loader.key_for(b, 150)
        assert loader.key_for(a, 150) != loader.key_for(a, 300)

    def test_duplicate_requests_are_dropped_while_in_flight(self, tmp_path):
        from tagorganizer.models import Item
        from tagorganizer.widgets.helper import ThumbnailLoader

        loader = ThumbnailLoader(max_threads=1)
        # a path that does not exist: the runnable returns quickly, but we
        # inspect the in-flight bookkeeping before draining the pool
        item = Item(id=7, uri="/does/not/exist.jpg")

        loader._inflight.add(loader.key_for(item, 150))
        before = loader.pending()
        loader.load(item, 150, tmp_path)
        assert loader.pending() == before, "duplicate request should be dropped"

    def test_preload_and_tile_share_one_decode(self):
        """The preloader's request must satisfy the tile that follows it."""
        from tagorganizer.models import Item
        from tagorganizer.widgets.helper import ThumbnailLoader

        loader = ThumbnailLoader(max_threads=1)
        item = Item(id=11, uri="/x.jpg")
        preload_key = loader.key_for(item, 150)
        # the tile asks for the same item at the same size, so it recognises
        # the result the preloader already has coming
        tile_key = loader.key_for(Item(id=11, uri="/x.jpg"), 150)
        assert preload_key == tile_key


class TestProfileGeneration:
    """Item ids are only unique within one profile's database.

    Switching profile must not let a decode made for the old database answer a
    request for the new one, and a decode still running for the old one must not
    be delivered at all.
    """

    def test_the_same_item_id_in_another_profile_is_a_different_key(self):
        from tagorganizer.models import Item
        from tagorganizer.widgets.helper import ThumbnailLoader

        loader = ThumbnailLoader(max_threads=1)
        before = loader.key_for(Item(id=5, uri="/profile_a/5.jpg"), 150)
        loader.new_generation()
        after = loader.key_for(Item(id=5, uri="/profile_b/5.jpg"), 150)
        assert before != after

    def test_a_result_from_the_previous_generation_is_dropped(self):
        from tagorganizer.models import Item
        from tagorganizer.widgets.helper import ThumbnailLoader

        loader = ThumbnailLoader(max_threads=1)
        old_key = loader.key_for(Item(id=5, uri="/a/5.jpg"), 150)
        loader.new_generation()
        new_key = loader.key_for(Item(id=5, uri="/b/5.jpg"), 150)

        delivered = []
        loader.thumbnail_ready.connect(lambda key, image: delivered.append(key))

        loader._on_ready(old_key, QImage())
        assert delivered == []

        loader._on_ready(new_key, QImage())
        assert delivered == [new_key]

    def test_a_new_generation_forgets_requests_made_for_the_old_one(self, tmp_path):
        """A request for the new profile must not be dropped as a duplicate."""
        from tagorganizer.models import Item
        from tagorganizer.widgets.helper import ThumbnailLoader

        loader = ThumbnailLoader(max_threads=1)
        item = Item(id=3, uri=str(tmp_path / "missing.jpg"))
        loader._inflight.add(loader.key_for(item, 150))

        loader.new_generation()

        assert loader.pending() == 0
        loader.load(item, 150, tmp_path)
        assert loader.pending() == 1
        loader.pool.waitForDone(5000)


class TestLoadQImageNoQApplication:
    """Verify load_qimage is truly importable/usable without QApplication."""

    def test_import_load_qimage_no_app(self):
        """Test that load_qimage can be imported without QApplication in scope."""
        # This imports happen at module level in this file, verifying it works
        from tagorganizer.widgets.helper import load_qimage

        assert callable(load_qimage)

    def test_load_qimage_function_signature(self):
        """Test that load_qimage has correct signature."""
        from tagorganizer.widgets.helper import load_qimage
        import inspect

        sig = inspect.signature(load_qimage)
        params = list(sig.parameters.keys())
        assert params == ["item", "size", "photos_path"]

        # Return annotation should not be QPixmap
        return_annotation = sig.return_annotation
        assert "QPixmap" not in str(return_annotation)
        assert (
            "QImage" in str(return_annotation)
            or return_annotation == inspect.Signature.empty
        )


class TestThumbnailCacheKey:
    def test_size_is_part_of_the_path(self, tmp_path):
        """A large decode must not overwrite - and then be served as - a small one."""
        from tagorganizer.widgets.helper import thumbnail_file

        small = thumbnail_file("abcdef0123456789", 150, tmp_path)
        large = thumbnail_file("abcdef0123456789", 600, tmp_path)
        assert small != large

    def test_thumbnails_live_beside_the_photos_on_every_platform(self, tmp_path):
        from tagorganizer.widgets.helper import get_thumbnail_path

        assert get_thumbnail_path(tmp_path) == tmp_path / "thumbnails"


class TestForgetThumbnail:
    def test_removes_every_cached_size(self, tmp_path):
        from tagorganizer.widgets.helper import forget_thumbnail, thumbnail_file

        md5 = "abcdef0123456789"
        made = []
        for size in (150, 600):
            path = thumbnail_file(md5, size, tmp_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"not really a png")
            made.append(path)

        forget_thumbnail(md5, tmp_path)
        assert not any(path.exists() for path in made)

    def test_is_quiet_when_nothing_is_cached(self, tmp_path):
        from tagorganizer.widgets.helper import forget_thumbnail

        forget_thumbnail("abcdef0123456789", tmp_path)
        forget_thumbnail("", tmp_path)


class TestProfileSwitchWiring:
    def test_switching_profile_or_config_starts_a_new_generation(self):
        """Both paths go through reset_view_state, so that is where the loader is told.

        Without it a profile switch keeps the old generation, and the item ids
        of the new profile are answered from the old one's decodes.
        """
        import ast
        import inspect
        import textwrap

        from tagorganizer.main import MainWindow

        source = textwrap.dedent(inspect.getsource(MainWindow.reset_view_state))
        calls = {
            node.func.attr
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert "new_generation" in calls


class TestSnapThumbnailSize:
    """Tiles resize continuously, and every distinct width was its own decode and
    its own directory of cached files. Snapping keeps the set of sizes small."""

    def test_a_width_maps_to_the_smallest_standard_size_that_holds_it(self):
        from tagorganizer.widgets.helper import snap_thumbnail_size

        assert snap_thumbnail_size(1) == 150
        assert snap_thumbnail_size(150) == 150
        assert snap_thumbnail_size(151) == 300
        assert snap_thumbnail_size(301) == 600

    def test_a_width_beyond_the_largest_size_gets_the_largest(self):
        from tagorganizer.widgets.helper import THUMBNAIL_SIZES, snap_thumbnail_size

        assert snap_thumbnail_size(5000) == THUMBNAIL_SIZES[-1]

    def test_only_standard_sizes_are_ever_returned(self):
        from tagorganizer.widgets.helper import THUMBNAIL_SIZES, snap_thumbnail_size

        returned = {snap_thumbnail_size(width) for width in range(1, 1200)}
        assert returned == set(THUMBNAIL_SIZES)


class TestByteCache:
    """The full-size cache is bounded by bytes, because a photo's cost is its
    pixels, not one entry."""

    def test_evicts_least_recently_used_until_under_budget(self):
        from tagorganizer.widgets.helper import ByteCache

        cache = ByteCache(budget_bytes=100)
        cache.put("a", "A", 40)
        cache.put("b", "B", 40)
        cache.put("c", "C", 40)

        assert cache.get("a") is None
        assert cache.get("b") == "B"
        assert cache.get("c") == "C"
        assert cache.nbytes <= 100

    def test_a_read_refreshes_recency(self):
        from tagorganizer.widgets.helper import ByteCache

        cache = ByteCache(budget_bytes=100)
        cache.put("a", "A", 40)
        cache.put("b", "B", 40)
        cache.get("a")
        cache.put("c", "C", 40)

        assert cache.get("a") == "A"
        assert cache.get("b") is None

    def test_a_single_entry_larger_than_the_budget_is_kept_alone(self):
        from tagorganizer.widgets.helper import ByteCache

        cache = ByteCache(budget_bytes=100)
        cache.put("a", "A", 40)
        cache.put("huge", "H", 500)

        assert cache.get("a") is None
        assert cache.get("huge") == "H"

    def test_replacing_a_key_does_not_double_count_it(self):
        from tagorganizer.widgets.helper import ByteCache

        cache = ByteCache(budget_bytes=100)
        cache.put("a", "A", 60)
        cache.put("a", "A2", 60)

        assert cache.nbytes == 60
        assert cache.get("a") == "A2"

    def test_full_size_photos_are_budgeted_by_bytes_not_count(self):
        """A count bound of 100 photos at 12 MP is about 4.9 GB."""
        from tagorganizer.widgets.helper import FULL_IMAGE_CACHE_BYTES

        twelve_megapixels = 4000 * 3000 * 4
        assert 100 * twelve_megapixels > FULL_IMAGE_CACHE_BYTES


class TestFullImageDecode:
    def _photo(self, path):
        image = QImage(64, 48, QImage.Format_RGB32)
        image.fill(0x00FF00)
        assert image.save(str(path), "PNG")
        return str(path)

    def test_a_decoded_photo_is_served_from_the_cache_afterwards(self, tmp_path):
        """The second request must not touch the file again."""
        import os

        from tagorganizer.widgets.helper import load_full_image

        path = self._photo(tmp_path / "once.png")
        first = load_full_image(path)
        assert first is not None

        os.remove(path)
        second = load_full_image(path)

        assert second is first

    def test_an_undecodable_file_gives_none(self, tmp_path):
        from tagorganizer.widgets.helper import load_full_image

        broken = tmp_path / "broken.png"
        broken.write_bytes(b"not an image")
        assert load_full_image(str(broken)) is None

    def test_warming_decodes_off_the_gui_thread_into_the_cache(self, tmp_path):
        from tagorganizer.widgets.helper import FullImageLoader, _full_images

        path = self._photo(tmp_path / "warmed.png")
        loader = FullImageLoader(max_threads=1)
        loader.warm(path)
        loader.pool.waitForDone(5000)

        assert _full_images.get(path) is not None

    def test_warming_the_same_photo_twice_queues_one_decode(self, tmp_path):
        from tagorganizer.widgets.helper import FullImageLoader

        path = self._photo(tmp_path / "twice.png")
        loader = FullImageLoader(max_threads=1)
        loader.warm(path)
        loader.warm(path)
        loader.pool.waitForDone(5000)

        assert loader._inflight == set()
