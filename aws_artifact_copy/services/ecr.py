import argparse
import hashlib
import json
import os
import sys
import tarfile

import trio

from ..common.botocore import (
    create_async_session,
    create_async_client,
    partial_client_methods,
)
from ..common.serialization import json_dumps_canonical


async def upload_file(ecr, limit, fctx) -> str:
    async with limit:
        with fctx as f:
            upload_config = await ecr.initiate_layer_upload()
            first_byte = 0
            hasher = hashlib.sha256()
            while chunk := f.read(upload_config["partSize"]):
                await ecr.upload_layer_part(
                    uploadId=upload_config["uploadId"],
                    partFirstByte=first_byte,
                    partLastByte=first_byte + len(chunk) - 1,
                    layerPartBlob=chunk,
                )
                first_byte = first_byte + len(chunk)
                hasher.update(chunk)
            digest = f"sha256:{hasher.hexdigest()}"
            try:
                await ecr.complete_layer_upload(
                    uploadId=upload_config["uploadId"],
                    layerDigests=[digest],
                )
            except ecr.exceptions.LayerAlreadyExistsException:
                # pushed from another process running concurrently, maybe?
                pass
    return digest


async def find_missing_layers(ecr, digests: list[str]) -> frozenset[str]:
    response = await ecr.batch_check_layer_availability(
        layerDigests=digests,
    )
    available_digests = frozenset(
        layer["layerDigest"]
        for layer in response["layers"]
        if layer["layerAvailability"] == "AVAILABLE"
    )
    return frozenset(digests) - available_digests


def parse_original_manifest(stream):
    manifest = json.load(stream)[0]
    yield {
        "path": manifest["Config"],
        # HACK assumption about streamLayeredImage format
        "digest": f"sha256:{manifest['Config'].split('.')[0]}",
    }
    for layer in manifest["Layers"]:
        yield {
            "path": layer,
            # HACK assumption about streamLayeredImage format
            "digest": f"sha256:{layer.split('/')[-2]}",
        }


async def upload_image(args: argparse.Namespace) -> str:
    async with create_async_client("ecr") as ecr_unwrapped:
        ecr = partial_client_methods(ecr_unwrapped, repositoryName=args.repository_name)

        with tarfile.open(args.source) as tf:
            index = {m.name: m for m in tf.getmembers()}

            with tf.extractfile(index["manifest.json"]) as f:
                layers = list(parse_original_manifest(f))

            manifest = json_dumps_canonical(
                {
                    "schemaVersion": 2,
                    "config": {
                        "mediaType": "application/vnd.oci.image.config.v1+json",
                        "digest": layers[0]["digest"],
                        "size": index[layers[0]["path"]].size,
                    },
                    "layers": [
                        {
                            "mediaType": "application/vnd.oci.image.layer.v1.tar",
                            "digest": layer["digest"],
                            "size": index[layer["path"]].size,
                        }
                        for layer in layers[1:]
                    ],
                }
            )
            manifest_digest = f"sha256:{hashlib.sha256(manifest).hexdigest()}"

            response = await ecr.batch_get_image(
                imageIds=[{"imageDigest": manifest_digest}],
            )
            if response["images"]:
                return manifest_digest

            missing_layers = await find_missing_layers(
                ecr, [layer["digest"] for layer in layers]
            )
            async with trio.open_nursery() as nursery:
                limit = trio.CapacityLimiter(args.upload_concurrency)
                for layer in layers:
                    if layer["digest"] not in missing_layers:
                        continue
                    nursery.start_soon(
                        upload_file, ecr, limit, tf.extractfile(index[layer["path"]])
                    )

            try:
                await ecr.put_image(
                    imageManifest=manifest.decode("utf-8"),
                    imageManifestMediaType="application/vnd.oci.image.manifest.v1+json",
                    imageDigest=manifest_digest,
                )
            except ecr.exceptions.ImageAlreadyExistsException:
                # pushed from another process running concurrently, maybe?
                pass
            return manifest_digest


def get_args(argv):
    parser = argparse.ArgumentParser(f"{os.path.basename(sys.argv[0])} ecr")
    parser.add_argument("source")
    parser.add_argument(
        "--format", choices=["nixpkgs-streamlayeredimage"], required=True
    )
    parser.add_argument("--repository-name", required=True)
    parser.add_argument("--upload-concurrency", type=int, default=10)
    return parser.parse_args(argv)


async def main(argv=None):
    args = get_args(argv)
    print(await upload_image(args))
