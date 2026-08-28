from contextguard.geometry import denormalize, ground_point, normalize, point_in_polygon, polygon_area

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def test_point_inside_square():
    assert point_in_polygon((5, 5), SQUARE) is True


def test_point_outside_square():
    assert point_in_polygon((15, 5), SQUARE) is False


def test_point_outside_negative():
    assert point_in_polygon((-1, -1), SQUARE) is False


def test_degenerate_polygon_is_never_inside():
    assert point_in_polygon((1, 1), [(0, 0), (1, 1)]) is False


def test_polygon_area_square():
    assert polygon_area(SQUARE) == 100.0


def test_normalize_denormalize_round_trip():
    pixel_poly = [(64.0, 48.0), (576.0, 48.0), (576.0, 432.0), (64.0, 432.0)]
    norm = normalize(pixel_poly, width=640, height=480)
    back = denormalize(norm, width=640, height=480)
    for (x1, y1), (x2, y2) in zip(pixel_poly, back):
        assert abs(x1 - x2) < 1e-6
        assert abs(y1 - y2) < 1e-6


def test_ground_point_is_bottom_center():
    assert ground_point((10, 20, 30, 100)) == (20, 100)
