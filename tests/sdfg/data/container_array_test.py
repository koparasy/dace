# Copyright 2019-2023 ETH Zurich and the DaCe authors. All rights reserved.
import ctypes
import dace
import numpy as np

from scipy import sparse


def test_read_struct_array():

    L, M, N, nnz = (dace.symbol(s) for s in ('L', 'M', 'N', 'nnz'))
    csr_obj = dace.data.Structure(dict(indptr=dace.int32[M + 1], indices=dace.int32[nnz], data=dace.float32[nnz]),
                                  name='CSRMatrix')
    csr_obj_view = dace.data.StructureView([('indptr', dace.int32[M + 1]), ('indices', dace.int32[nnz]),
                                            ('data', dace.float32[nnz])],
                                           name='CSRMatrix',
                                           transient=True)

    sdfg = dace.SDFG('array_of_csr_to_dense')

    sdfg.add_datadesc('A', csr_obj[L])
    sdfg.add_array('B', [L, M, N], dace.float32)

    sdfg.add_datadesc('vcsr', csr_obj_view)
    sdfg.add_view('vindptr', csr_obj.members['indptr'].shape, csr_obj.members['indptr'].dtype)
    sdfg.add_view('vindices', csr_obj.members['indices'].shape, csr_obj.members['indices'].dtype)
    sdfg.add_view('vdata', csr_obj.members['data'].shape, csr_obj.members['data'].dtype)

    state = sdfg.add_state()

    A = state.add_access('A')
    B = state.add_access('B')

    bme, bmx = state.add_map('b', dict(b='0:L'))
    bme.map.schedule = dace.ScheduleType.Sequential

    vcsr = state.add_access('vcsr')
    indptr = state.add_access('vindptr')
    indices = state.add_access('vindices')
    data = state.add_access('vdata')

    state.add_memlet_path(A, bme, vcsr, dst_conn='views', memlet=dace.Memlet(data='A', subset='b'))
    state.add_edge(vcsr, None, indptr, 'views', memlet=dace.Memlet.from_array('vcsr.indptr', csr_obj.members['indptr']))
    state.add_edge(vcsr,
                   None,
                   indices,
                   'views',
                   memlet=dace.Memlet.from_array('vcsr.indices', csr_obj.members['indices']))
    state.add_edge(vcsr, None, data, 'views', memlet=dace.Memlet.from_array('vcsr.data', csr_obj.members['data']))

    ime, imx = state.add_map('i', dict(i='0:M'))
    jme, jmx = state.add_map('idx', dict(idx='start:stop'))
    jme.add_in_connector('start')
    jme.add_in_connector('stop')
    t = state.add_tasklet('indirection', {'j', '__val'}, {'__out'}, '__out[i, j] = __val')

    state.add_memlet_path(indptr, ime, jme, memlet=dace.Memlet(data='vindptr', subset='i'), dst_conn='start')
    state.add_memlet_path(indptr, ime, jme, memlet=dace.Memlet(data='vindptr', subset='i+1'), dst_conn='stop')
    state.add_memlet_path(indices, ime, jme, t, memlet=dace.Memlet(data='vindices', subset='idx'), dst_conn='j')
    state.add_memlet_path(data, ime, jme, t, memlet=dace.Memlet(data='vdata', subset='idx'), dst_conn='__val')
    state.add_memlet_path(t,
                          jmx,
                          imx,
                          bmx,
                          B,
                          memlet=dace.Memlet(data='B', subset='b, 0:M, 0:N', volume=1),
                          src_conn='__out')

    func = sdfg.compile()

    rng = np.random.default_rng(42)
    A = np.ndarray((10, ), dtype=sparse.csr_matrix)
    dace_A = np.ndarray((10, ), dtype=ctypes.c_void_p)
    B = np.zeros((10, 20, 20), dtype=np.float32)

    ctypes_A = []
    for b in range(10):
        A[b] = sparse.random(20, 20, density=0.1, format='csr', dtype=np.float32, random_state=rng)
        ctypes_obj = csr_obj.dtype._typeclass.as_ctypes()(indptr=A[b].indptr.__array_interface__['data'][0],
                                                          indices=A[b].indices.__array_interface__['data'][0],
                                                          data=A[b].data.__array_interface__['data'][0])
        ctypes_A.append(ctypes_obj)  # This is needed to keep the object alive ...
        dace_A[b] = ctypes.addressof(ctypes_obj)

    func(A=dace_A, B=B, L=A.shape[0], M=A[0].shape[0], N=A[0].shape[1], nnz=A[0].nnz)
    ref = np.ndarray((10, 20, 20), dtype=np.float32)
    for b in range(10):
        ref[b] = A[b].toarray()

    assert np.allclose(B, ref)


def test_write_struct_array():

    L, M, N, nnz = (dace.symbol(s) for s in ('L', 'M', 'N', 'nnz'))
    csr_obj = dace.data.Structure([('indptr', dace.int32[M + 1]), ('indices', dace.int32[nnz]),
                                   ('data', dace.float32[nnz])],
                                  name='CSRMatrix')
    csr_obj_view = dace.data.StructureView(dict(indptr=dace.int32[M + 1],
                                                indices=dace.int32[nnz],
                                                data=dace.float32[nnz]),
                                           name='CSRMatrix',
                                           transient=True)

    sdfg = dace.SDFG('array_dense_to_csr')

    sdfg.add_array('A', [L, M, N], dace.float32)
    sdfg.add_datadesc('B', csr_obj[L])

    sdfg.add_datadesc('vcsr', csr_obj_view)
    sdfg.add_view('vindptr', csr_obj.members['indptr'].shape, csr_obj.members['indptr'].dtype)
    sdfg.add_view('vindices', csr_obj.members['indices'].shape, csr_obj.members['indices'].dtype)
    sdfg.add_view('vdata', csr_obj.members['data'].shape, csr_obj.members['data'].dtype)

    # Make If
    if_before = sdfg.add_state('if_before')
    if_guard = sdfg.add_state('if_guard')
    if_body = sdfg.add_state('if_body')
    if_after = sdfg.add_state('if_after')
    sdfg.add_edge(if_before, if_guard, dace.InterstateEdge())
    sdfg.add_edge(if_guard, if_body, dace.InterstateEdge(condition='A[k, i, j] != 0'))
    sdfg.add_edge(if_body, if_after, dace.InterstateEdge(assignments={'idx': 'idx + 1'}))
    sdfg.add_edge(if_guard, if_after, dace.InterstateEdge(condition='A[k, i, j] == 0'))
    A = if_body.add_access('A')
    vcsr = if_body.add_access('vcsr')
    B = if_body.add_access('B')
    indices = if_body.add_access('vindices')
    data = if_body.add_access('vdata')
    if_body.add_edge(A, None, data, None, dace.Memlet(data='A', subset='k, i, j', other_subset='idx'))
    if_body.add_edge(data, 'views', vcsr, None, dace.Memlet(data='vcsr.data', subset='0:nnz'))
    t = if_body.add_tasklet('set_indices', {}, {'__out'}, '__out = j')
    if_body.add_edge(t, '__out', indices, None, dace.Memlet(data='vindices', subset='idx'))
    if_body.add_edge(indices, 'views', vcsr, None, dace.Memlet(data='vcsr.indices', subset='0:nnz'))
    if_body.add_edge(vcsr, 'views', B, None, dace.Memlet(data='B', subset='k'))
    # Make For Loop  for j
    j_before, j_guard, j_after = sdfg.add_loop(None,
                                               if_before,
                                               None,
                                               'j',
                                               '0',
                                               'j < N',
                                               'j + 1',
                                               loop_end_state=if_after)
    # Make For Loop  for i
    i_before, i_guard, i_after = sdfg.add_loop(None, j_before, None, 'i', '0', 'i < M', 'i + 1', loop_end_state=j_after)
    sdfg.start_state = sdfg.node_id(i_before)
    i_before_guard = sdfg.edges_between(i_before, i_guard)[0]
    i_before_guard.data.assignments['idx'] = '0'
    vcsr = i_guard.add_access('vcsr')
    B = i_guard.add_access('B')
    indptr = i_guard.add_access('vindptr')
    t = i_guard.add_tasklet('set_indptr', {}, {'__out'}, '__out = idx')
    i_guard.add_edge(t, '__out', indptr, None, dace.Memlet(data='vindptr', subset='i'))
    i_guard.add_edge(indptr, 'views', vcsr, None, dace.Memlet(data='vcsr.indptr', subset='0:M+1'))
    i_guard.add_edge(vcsr, 'views', B, None, dace.Memlet(data='B', subset='k'))
    vcsr = i_after.add_access('vcsr')
    B = i_after.add_access('B')
    indptr = i_after.add_access('vindptr')
    t = i_after.add_tasklet('set_indptr', {}, {'__out'}, '__out = nnz')
    i_after.add_edge(t, '__out', indptr, None, dace.Memlet(data='vindptr', subset='M'))
    i_after.add_edge(indptr, 'views', vcsr, None, dace.Memlet(data='vcsr.indptr', subset='0:M+1'))
    i_after.add_edge(vcsr, 'views', B, None, dace.Memlet(data='B', subset='k'))

    k_before, k_guard, k_after = sdfg.add_loop(None, i_before, None, 'k', '0', 'k < L', 'k + 1', loop_end_state=i_after)

    func = sdfg.compile()

    rng = np.random.default_rng(42)
    B = np.ndarray((10, ), dtype=sparse.csr_matrix)
    dace_B = np.ndarray((10, ), dtype=ctypes.c_void_p)
    A = np.empty((10, 20, 20), dtype=np.float32)

    ctypes_B = []
    for b in range(10):
        B[b] = sparse.random(20, 20, density=0.1, format='csr', dtype=np.float32, random_state=rng)
        A[b] = B[b].toarray()
        nnz = B[b].nnz
        B[b].indptr[:] = -1
        B[b].indices[:] = -1
        B[b].data[:] = -1
        ctypes_obj = csr_obj.dtype._typeclass.as_ctypes()(indptr=B[b].indptr.__array_interface__['data'][0],
                                                          indices=B[b].indices.__array_interface__['data'][0],
                                                          data=B[b].data.__array_interface__['data'][0])
        ctypes_B.append(ctypes_obj)  # This is needed to keep the object alive ...
        dace_B[b] = ctypes.addressof(ctypes_obj)

    func(A=A, B=dace_B, L=B.shape[0], M=B[0].shape[0], N=B[0].shape[1], nnz=nnz)
    for b in range(10):
        assert np.allclose(A[b], B[b].toarray())


def test_jagged_container_array():
    N = dace.symbol('N')
    M = dace.symbol('M')
    sdfg = dace.SDFG('tester')
    sdfg.add_datadesc('A', dace.data.ContainerArray(dace.float64[N], [M]))
    sdfg.add_view('v', [N], dace.float64)
    sdfg.add_array('B', [1], dace.float64)

    # Make a state where the container array is first viewed with index i (i.e., dereferencing double** to double*)
    # and then the view is accessed with index j
    state = sdfg.add_state()
    me, mx = state.add_map('outer', dict(i='0:M'))
    ime, imx = state.add_map('inner', dict(j='0:i'))
    t = state.add_tasklet('add', {'inp'}, {'out'}, 'out = inp')
    r = state.add_read('A')
    v = state.add_access('v')
    w = state.add_write('B')
    state.add_memlet_path(r, me, v, memlet=dace.Memlet('A[i]'), dst_conn='views')
    state.add_memlet_path(v, ime, t, memlet=dace.Memlet('v[j]'), dst_conn='inp')
    state.add_memlet_path(t, imx, mx, w, memlet=dace.Memlet('B[0]', wcr='lambda a,b: a+b'), src_conn='out')

    m = 20
    # Create a ctypes array of arrays
    jagged_array = (ctypes.POINTER(ctypes.c_double) * m)(*[(ctypes.c_double * i)(*np.random.rand(i))
                                                           for i in range(1, m + 1)])
    ref = 0
    for i in range(m):
        for j in range(i):
            ref += jagged_array[i][j]

    B = np.zeros([1])
    sdfg(A=jagged_array, B=B, M=m)
    assert np.allclose(ref, B[0])


def test_two_levels():
    N = dace.symbol('N')
    M = dace.symbol('M')
    K = dace.symbol('K')
    sdfg = dace.SDFG('tester')
    sdfg.add_datadesc('A', dace.float64[N][M][K])
    desc = dace.data.ContainerView(dace.float64[N], [M], True)
    sdfg.add_datadesc('v', desc)
    sdfg.add_view('vv', [N], dace.float64)
    sdfg.add_array('B', [1], dace.float64)

    # Make a state where the container is viewed twice in a row
    state = sdfg.add_state()
    r = state.add_read('A')
    v = state.add_access('v')
    v.add_in_connector('views')
    vv = state.add_access('vv')
    vv.add_in_connector('views')
    w = state.add_write('B')
    state.add_edge(r, None, v, 'views', dace.Memlet('A[1]'))
    state.add_edge(v, None, vv, 'views', dace.Memlet('v[2]'))
    state.add_edge(vv, None, w, None, dace.Memlet('vv[3]'))

    # Create a ctypes array of arrays
    jagged_array = (ctypes.POINTER(ctypes.POINTER(ctypes.c_double)) * 5)(
        *[
            #
            (ctypes.POINTER(ctypes.c_double) * 5)(
                *[
                    #
                    (ctypes.c_double * 5)(*np.random.rand(5)) for _ in range(5)
                    #
                ]) for _ in range(5)
            #
        ])

    ref = jagged_array[1][2][3]

    B = np.zeros([1])
    sdfg(A=jagged_array, B=B)
    assert np.allclose(ref, B[0])


if __name__ == '__main__':
    test_read_struct_array()
    test_write_struct_array()
    test_jagged_container_array()
    test_two_levels()
