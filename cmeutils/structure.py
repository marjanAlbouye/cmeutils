from cmeutils import gsd_utils
import freud
import gsd
import gsd.hoomd
import numpy as np


def q_from_vectors(b, a=np.array([0,0,1])):
    """Calculate the quaternion representing the rotation from a to b."""
    q = np.empty(4)
    q[:3] = np.cross(a,b)
    q[3] = np.dot(a,b)
    q /= np.linalg.norm(q)
    return q


def get_quaternions(n_views = 20):
    """Get the quaternions for the specified number of views."""
    ga = np.pi * (3 - 5**0.5)
    theta = ga * np.arange(n_views-3)
    z = np.linspace(1 - 1/(n_views-3), 1/(n_views-3), n_views-3)
    radius = np.sqrt(1 - z * z)
    points = np.zeros((n_views, 3))
    points[:-3,0] = radius * np.cos(theta)
    points[:-3,1] = radius * np.sin(theta)
    points[:-3,2] = z
    # face on
    points[-3] = np.array([0,0,1])
    # edge on
    points[-2] = np.array([0,1,1])
    # corner on
    points[-1] = np.array([1,1,1])
    return [q_from_vectors(i) for i in points]


def gsd_rdf(
    gsdfile,
    A_name,
    B_name,
    start=0,
    stop=None,
    r_max=None,
    r_min=0,
    bins=100,
    exclude_bonded=True,
):
    """Compute intermolecular RDF from a GSD file.

    This function calculates the radial distribution function given a GSD file
    and the names of the particle types. By default it will calculate the RDF
    for the entire trajectory.

    It is assumed that the bonding, number of particles, and simulation box do
    not change during the simulation.

    Parameters
    ----------
    gsdfile : str
        Filename of the GSD trajectory.
    A_name, B_name : str
        Name(s) of particles between which to calculate the RDF (found in
        gsd.hoomd.Snapshot.particles.types)
    start : int
        Starting frame index for accumulating the RDF. Negative numbers index
        from the end. (default 0)
    stop : int
        Final frame index for accumulating the RDF. If None, the last frame
        will be used. (default None)
    r_max : float
        Maximum radius of RDF. If None, half of the maximum box size is used.
        (default None)
    r_min : float
        Minimum radius of RDF. (default 0)
    bins : int
        Number of bins to use when calculating the RDF. (default 100)
    exclude_bonded : bool
        Whether to remove particles in same molecule from the neighbor list.
        (default True)

    Returns
    -------
    (freud.density.RDF, float)
    """
    if not stop:
        stop = -1

    with gsd.hoomd.open(gsdfile, mode="rb") as trajectory:
        snap = trajectory[0]

        if r_max is None:
            # Use a value just less than half the maximum box length.
            r_max = np.nextafter(
                np.max(snap.configuration.box[:3]) * 0.5, 0, dtype=np.float32
            )

        rdf = freud.density.RDF(bins=bins, r_max=r_max, r_min=r_min)

        type_A = snap.particles.typeid == snap.particles.types.index(A_name)
        type_B = snap.particles.typeid == snap.particles.types.index(B_name)

        if exclude_bonded:
            molecules = gsd_utils.snap_molecule_cluster(snap=snap)
            molecules_A = molecules[type_A]
            molecules_B = molecules[type_B]

        for snap in trajectory[start:stop]:
            A_pos = snap.particles.position[type_A]
            if A_name == B_name:
                B_pos = A_pos
                exclude_ii = True
            else:
                B_pos = snap.particles.position[type_B]
                exclude_ii = False

            box = snap.configuration.box
            system = (box, A_pos)
            aq = freud.locality.AABBQuery.from_system(system)
            nlist = aq.query(
                B_pos, {"r_max": r_max, "exclude_ii": exclude_ii}
            ).toNeighborList()

            if exclude_bonded:
                pre_filter = len(nlist)
                nlist.filter(
                    molecules_A[nlist.point_indices]
                    != molecules_B[nlist.query_point_indices]
                )
                post_filter = len(nlist)

            rdf.compute(aq, neighbors=nlist, reset=False)

        normalization = post_filter / pre_filter if exclude_bonded else 1
        return rdf, normalization
