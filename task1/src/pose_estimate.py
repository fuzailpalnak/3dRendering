import math
import os
from typing import Union

import cv2
import numpy as np

from task1.src.dlt import RANSAC
from task1.src.util import draw_pairs, draw_key_points
from task1.src.ops import ransac, find_features, match_features

MODEL_IMAGE = (
    r"/home/palnak/Workspace/Studium/msc/sem3/assignment/AR/task1/data/surface_5.jpeg"
)
MP = r"../output/matches"
KP = r"../output/keypoints"

if not os.path.exists(KP):
    os.makedirs(KP)

if not os.path.exists(MP):
    os.makedirs(MP)

DEBUG = True
# WEBCAM_INTRINSIC = np.array(
#     [
#         [740.45702626, 0.0, 254.03659584],
#         [0.0, 787.25184509, 175.67665548],
#         [0.0, 0.0, 1.0],
#     ]
# )

WEBCAM_INTRINSIC = np.array([[800, 0, 320], [0, 800, 240], [0, 0, 1]])
WEBCAM_DST = np.array(
    [[-1.38550017e00, 3.99507333e00, -2.90393843e-03, 2.41582743e-02, -4.97242005e00]]
)

IPHONE_14_PRO = np.array(
    [
        [6.23649154e02, 0.00000000e00, 1.45491457e03],
        [0.00000000e00, 6.24325606e02, 1.94913052e03],
        [0.00000000e00, 0.00000000e00, 1.00000000e00],
    ]
)


def get_extended_RT(A, H):
    # finds r3 and appends
    # A is the intrinsic mat, and H is the homography estimated
    H = np.float64(H)  # for better precision
    A = np.float64(A)
    R_12_T = np.linalg.inv(A).dot(H)

    r1 = np.float64(R_12_T[:, 0])  # col1
    r2 = np.float64(R_12_T[:, 1])  # col2
    T = R_12_T[:, 2]  # translation

    # ideally |r1| and |r2| should be same
    # since there is always some error we take square_root(|r1||r2|) as the normalization factor
    norm = np.float64(
        math.sqrt(np.float64(np.linalg.norm(r1)) * np.float64(np.linalg.norm(r2)))
    )

    r3 = np.cross(r1, r2) / (norm)
    R_T = np.zeros((3, 4))
    R_T[:, 0] = r1
    R_T[:, 1] = r2
    R_T[:, 2] = r3
    R_T[:, 3] = T
    return R_T


def projection_matrix(camera_parameters, homography):
    """
    From the camera calibration matrix and the estimated homography
    compute the 3D projection matrix
    """
    # Compute rotation along the x and y axis as well as the translation
    homography = homography * (-1)
    rot_and_transl = np.dot(np.linalg.inv(camera_parameters), homography)
    col_1 = rot_and_transl[:, 0]
    col_2 = rot_and_transl[:, 1]
    col_3 = rot_and_transl[:, 2]
    # normalise vectors
    l = math.sqrt(np.linalg.norm(col_1, 2) * np.linalg.norm(col_2, 2))
    rot_1 = col_1 / l
    rot_2 = col_2 / l
    translation = col_3 / l
    # compute the orthonormal basis
    c = rot_1 + rot_2
    p = np.cross(rot_1, rot_2)
    d = np.cross(c, p)
    rot_1 = np.dot(
        c / np.linalg.norm(c, 2) + d / np.linalg.norm(d, 2), 1 / math.sqrt(2)
    )
    rot_2 = np.dot(
        c / np.linalg.norm(c, 2) - d / np.linalg.norm(d, 2), 1 / math.sqrt(2)
    )
    rot_3 = np.cross(rot_1, rot_2)
    # finally, compute the 3D projection matrix from the model to the current frame
    projection = np.stack((rot_1, rot_2, rot_3, translation)).T
    return projection


def run(pth: Union[str, int] = 0):
    cap = cv2.VideoCapture(pth)

    # Check if the webcam is opened correctly
    if not cap.isOpened():
        raise IOError("Cannot open THE provided")

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    # writer = cv2.VideoWriter(
    #     "pose_estimation.mp4", cv2.VideoWriter_fourcc(*"DIVX"), cap.get(cv2.CAP_PROP_FPS), (width, height)
    # )

    i = 0
    model_image = cv2.imread(MODEL_IMAGE)
    model_image = cv2.cvtColor(model_image, cv2.COLOR_BGR2GRAY)

    while cap.isOpened():
        print(f"\x1b[2K\r└──> Frame {i + 1}", end="")
        _, frame = cap.read()

        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        h, w = frame.shape[0:2]
        model_image = cv2.resize(model_image, (w, h), interpolation=cv2.INTER_AREA)
        # model_image = cv2.rotate(model_image, cv2.ROTATE_90_CLOCKWISE)
        model_image_key_points, model_image_desc = find_features(model_image)

        # INTEREST POINT DETECTION
        f_key_points, f_desc = find_features(frame)
        if DEBUG:
            cv2.imwrite(
                os.path.join(KP, f"{i}_keypoints-1.png"),
                cv2.drawKeypoints(model_image, model_image_key_points, model_image),
            )
            cv2.imwrite(
                os.path.join(KP, f"{i}_keypoints-2.png"),
                cv2.drawKeypoints(frame.copy(), f_key_points, frame.copy()),
            )

        # FEATURE MATCHING
        matches = match_features(model_image_desc, f_desc)
        point_map = np.array(
            [
                [
                    model_image_key_points[match.queryIdx].pt[0],
                    model_image_key_points[match.queryIdx].pt[1],
                    f_key_points[match.trainIdx].pt[0],
                    f_key_points[match.trainIdx].pt[1],
                ]
                for match in matches
            ]
        )

        # HOMOGRAPHY ESTIMATION
        homography, inliers = ransac(point_map)

        if DEBUG:
            matches_sorted = sorted(matches, key=lambda x: x.distance)
            src_pts = np.float32(
                [model_image_key_points[m.queryIdx].pt for m in matches_sorted]
            ).reshape(-1, 1, 2)
            dst_pts = np.float32(
                [f_key_points[m.trainIdx].pt for m in matches_sorted]
            ).reshape(-1, 1, 2)

            opencv_homography, mask = cv2.findHomography(
                src_pts, dst_pts, cv2.RANSAC, 5.0
            )
            print("homography by OPENCV")
            print(f"└──>{opencv_homography}")

            print("\nEstimated homography")
            print(f"└──>{homography}")

            pairs_img = draw_pairs(frame.copy(), point_map, inliers)
            cv2.imwrite(
                os.path.join(MP, f"{str(i)}.png"),
                pairs_img,
            )

            mapping_img = draw_key_points(
                model_image, frame.copy(), point_map, pairs=inliers
            )
            cv2.imwrite(
                os.path.join(KP, f"{i}_mapping.png"),
                mapping_img,
            )

        if homography is not None:
            r_t = get_extended_RT(WEBCAM_INTRINSIC, opencv_homography)
            transformation = WEBCAM_INTRINSIC.dot(r_t)

            projection = np.dot(
                WEBCAM_INTRINSIC, projection_matrix(WEBCAM_INTRINSIC, homography)
            )
            axis = np.float32(
                [
                    [0, 0, 0],
                    [0, 3, 0],
                    [3, 3, 0],
                    [3, 0, 0],
                    [0, 0, -3],
                    [0, 3, -3],
                    [3, 3, -3],
                    [3, 0, -3],
                ]
            )
            # objectPoints = 3 * axis
            dst = cv2.perspectiveTransform(axis.reshape(-1, 1, 3), projection)
            imgpts = np.int32(dst)
            #
            # num, Rs, Ts, Ns = cv2.decomposeHomographyMat(homography, WEBCAM_INTRINSIC)
            # imgpts, jac = cv2.projectPoints(
            #     axis, Rs[1], Ts[1], WEBCAM_INTRINSIC, WEBCAM_DST
            # )

            imgpts = np.int32(imgpts).reshape(-1, 2)
            #
            # # draw ground floor in green
            img = cv2.drawContours(frame.copy(), [imgpts[:4]], -1, (0, 255, 0), -1)

            # draw pillars in blue color
            for i, j in zip(range(4), range(4, 8)):
                img = cv2.line(img, tuple(imgpts[i]), tuple(imgpts[j]), (255), 3)

            # draw top layer in red color
            img = cv2.drawContours(img, [imgpts[4:]], -1, (0, 0, 255), 3)

        i += 1
        # cv2.imwrite(
        #     os.path.join(MP, f"{i}_mapping_polylines.png"),
        #     poly_lines,
        # )
        cv2.imshow("img", mapping_img)
        if cv2.waitKey(1) == 27:
            break

        # cv2.imshow("img", img)
        # cv2.imwrite("her.png", img)
        # writer.write(img)


run(0)
