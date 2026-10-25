import generate_synthetic


def test_same_seed_identical_files(tmp_path):
    a = generate_synthetic.write(300, 42, tmp_path / "a")
    b = generate_synthetic.write(300, 42, tmp_path / "b")
    for pa, pb in zip(a, b, strict=True):
        assert pa.read_bytes() == pb.read_bytes()


def test_committed_sample_matches_generator(tmp_path):
    from tests.conftest import SAMPLES

    csv_path, subject_path = generate_synthetic.write(300, 42, tmp_path)
    assert csv_path.read_bytes() == (SAMPLES / "mls_sample.csv").read_bytes()
    assert subject_path.read_bytes() == (SAMPLES / "subject.yaml").read_bytes()
