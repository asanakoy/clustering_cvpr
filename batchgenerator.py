# --
# Copyright (c) 2016 Miguel Bautista
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
# ++

import numpy as np
from clique import Clique
import time

class BatchGenerator(object):

    """
    This class encapsulates the logic and operations to generate batches of cliques to train a CNN.
    """

    def __init__(self, **kwargs):
        """
        """


        default_params = {
            'simMatrix': None,
            'flipMatrix': None,
            'seqNames': None,
            'imagePath': None,
            'pathToFolder': None,
            'init_nCliques': None,
            'nSamples': None,
            'anchors': None,
            '_curr_label': 0,
        }

        default_params.update(kwargs)
        for k in default_params.keys():
            self.__setattr__(k, default_params[k])
        self._check_params()

    def _check_params(self):
        """
        Param checker
        :return:
        """
        assert self.simMatrix is not None, "Similarity matrix is empty"

    def generateBatches(self, init_nbatches=100):
        """
        This function loops over batches and calls the batch computation
        :return:
        """
        batches = []
        assert init_nbatches >= len(self.anchors['anchor']), "Number of batches must be larger than the number of anchors"
        for batch_id in range(init_nbatches):
            print "Computing batch {}".format(batch_id)
            if batch_id <= len(self.anchors):
                seed_sample = int(self.anchors['anchor'][batch_id][0])
            else:
                seed_sample = np.random.randint(self.simMatrix.shape[0])
            batches.append(self.computeBatch(seed_sample))
        return batches

    def computeBatch(self, seed):
        """
        Compute a batch of cliques performing temporal augmentation in each clique
        :param seed: Seed used to compute the first clique
        :return: a list of cliques (a batch)
        """
        nClique = 0
        batch = []
        constraints = 'nClique < self.init_nCliques'
        while eval(constraints):
            clique = self.computeClique(seed)
            self.cliquePurification(clique)
            # Probably better do temporal augmentation after transitive growing
            self.temporalAugmentation(clique)

            # Set label of clique and add to batch if it has more than 1 sample
            if clique.samples.shape[0] > 1:
                clique.label = self._curr_label
                self._curr_label += 1
                batch.append(clique)

            seed = self.findDissimilarSeed(batch)
            nClique += 1

        # batch = self.transitiveCliqueComputation(batch)
        return batch

    def computeClique(self, seed):
        """
        This function stores the logic of clique computation. It adds the point p that maximizes the average
        similarity to the current clique and does not belong to an already used sequence
        :param seed:
        :return: clique
        """

        clique = Clique(self.pathToFolder, self.simMatrix.shape[0])
        clique.addSample(seed, self.flipMatrix[seed, seed], self.imagePath[seed])
        self.updateAvailableIndices(clique, seed)

        nSamples = 1
        constraints = 'nSamples < self.nSamples'
        while eval(constraints):
            idx_avail = np.where(clique.availableIndices)[0]
            p = idx_avail[np.mean(self.simMatrix[clique.samples, idx_avail], axis=0).argmax()]
            f = self.calculateFlip(clique, p)
            clique.addSample(p, f, self.imagePath[p])
            clique.weight = np.linalg.norm(self.simMatrix[clique.samples, clique.samples]) / (len(clique.samples) ** 2.0)
            self.updateAvailableIndices(clique, p)
            nSamples += 1
        return clique

    def updateAvailableIndices(self, clique, sample, temporalWindow=0):
        """
        Update the indicator vector of available samples to include in clique. Constraining so that a clique does not
        include two samples of the same sequence
        :param avail: current indicator vector
        :param sample:
        :return:
        """
        # If there is no sequence structure update is not done
        if self.seqNames is None:
            return

        if temporalWindow:
            clique.availableIndices[sample-temporalWindow: sample+temporalWindow] = False
        else:
            # No temporal window, take the whole sequence
            ind_not_seq = np.asarray(self.seqNames) != np.asarray([self.seqNames[sample]] * self.simMatrix.shape[0])
            clique.availableIndices = ~((~np.asarray(clique.availableIndices)) | (~np.asarray(ind_not_seq)))

    def cliquePurification(self, clique):
        """
        Purify a clique by replacing an assignment with a non-assigned  point that maximizes average similarity to clique
        :param clique:
        :return:
        """
        # For each point in the clique, compute its avg similarity to the clique (substracting self sim)
        avgSelfSim = np.zeros(clique.samples.shape[0])
        init_samples = clique.samples[:]
        for idx, sample in enumerate(clique.samples):
            aux_samples = init_samples
            aux_samples = np.delete(aux_samples, idx)
            avgSelfSim[idx] = np.max(self.simMatrix[aux_samples, sample], axis=0)

        sorted_self_sim = avgSelfSim.argsort()
        topk = int(sorted_self_sim.shape[0] * 1)
        for idx in sorted_self_sim[:topk]:

            # Sort points with respect to the avg similarity to the current clique minus the temptative point to extract
            aux_samples = init_samples
            aux_samples = np.delete(aux_samples, idx)
            avgSim = np.max(self.simMatrix[:, aux_samples], axis=1)
            nearest_samples = avgSim.reshape(1, -1).argsort()[0][::-1]
            for i in nearest_samples:

                # Filter points that are already assigned to the clique or are not available
                if i in clique.samples or not clique.availableIndices[i]:
                    continue
                # If the non assigned point i has better avg similarity to the clique than "sample", replace assignment
                #  and jump to next point
                if avgSim[i] > avgSelfSim[idx]:
                    self.replaceAssigment(clique, idx, i)
                    break





    def findDissimilarSeed(self, batch):
        """
        Find the seed that minimizes the min-similarity (top 5% least similar) with the current batch
        :param batch: Current batch of cliques
        :return:
        """
        # TODO: Find seed which is at least more dissimilar that the most dissimilar points in a clique

        topPercent = 0.05
        allIdxs = np.empty(0, dtype=np.int32)
        for clique in batch:
            allIdxs = np.append(allIdxs, clique.samples)
        sortedIdxs = np.min(self.simMatrix[allIdxs.reshape(-1, 1)], axis=0).argsort()
        seed = np.random.choice(sortedIdxs[:int(np.ceil(self.simMatrix.shape[0] * topPercent))][0])
        return seed

    def transitiveCliqueComputation(self, batch):
        """
        Filter a clique using transitivity constraints.

        :param clique: clique to be filtered
        :return: a filtered clique (which can vary in size)
        """

        sigmaMult = 1.5
        voting_threshold = 0.95
        factor = 1.5

        for i in range(self.simMatrix.shape[0]):

            # Do not account the points already assigned
            for clique in batch:
                if i in clique.samples:
                    continue

            minSimtoClique = np.empty(len(batch), dtype=np.int32)
            for idx, clique in enumerate(batch):
                minSimtoClique[idx] = np.min(self.simMatrix[clique.samples, i])
            idx_sorting = minSimtoClique.argsort()
            minSimtoClique.sort()

            # If one clique is much closer than the others (ie. point i is in the local neighbourhood a clique)
            if (minSimtoClique[-1] > (minSimtoClique[-2] * factor)) and batch[idx_sorting[-1]].availableIndices[i]:

                # Check distances to points in clique and indicate the inliers in sigma range (ie. each sample in the
                # clique casts a vote for sample i whether it should be included)
                selectedClique = batch[idx_sorting[-1]]
                simToClique = self.simMatrix[selectedClique.samples, i]
                inlierInd = np.asarray((simToClique - np.mean(simToClique)) >= (-sigmaMult * np.std(simToClique)), dtype=np.bool)

                # Include sample if voting is higher than a threshold
                if (np.sum(inlierInd) / inlierInd.shape[0]) >= voting_threshold:
                    self.updateAvailableIndices(selectedClique, i, temporalWindow=10)
                    f = self.calculateFlip(selectedClique, i)
                    selectedClique.addSample(i, f, self.imagePath[i])
        return batch

    def temporalAugmentation(self, clique):
        """
        Do temporal augmentation by adding to the clique the immediate previous and next frame for each sample. Check
        cases where frame is either the first or last frame of a sequence
        :param clique:
        :return:
        """
        # If there is no sequence structure temporal augmentation is not done
        if self.seqNames is None:
            return
        for frame_id in clique.samples:
            idxsSeq = np.where((np.asarray(self.seqNames) == np.tile(np.asarray(self.seqNames[frame_id[0]]),
                                                                     self.simMatrix.shape[0])) == True)[0]
            if frame_id == idxsSeq[0]:
                clique.addSample(frame_id + 1, int(clique.isflipped[-1]), self.imagePath[frame_id[0] + 1])
            else:
                clique.addSample(frame_id - 1, int(clique.isflipped[-1]), self.imagePath[frame_id[0] - 1])

    def calculateFlip(self, clique, new_sample):
        return int(np.mean(self.flipMatrix[clique.samples, new_sample]) >= 0.5)

    def replaceAssigment(self, clique, cliqueidxtoremove, generalIdxtoAdd):

        # Remove old sample and update params
        idxsSeq = np.where((np.asarray(self.seqNames) == np.asarray(
            [self.seqNames[clique.samples[cliqueidxtoremove][0]]] * self.simMatrix.shape[0])) == True)[0]
        clique.availableIndices[idxsSeq] = True
        clique.removeSample(cliqueidxtoremove)

        #  Add sample and update params
        f = self.calculateFlip(clique, generalIdxtoAdd)
        clique.addSample(generalIdxtoAdd, f, self.imagePath[generalIdxtoAdd])
        clique.weight = np.linalg.norm(self.simMatrix[clique.samples, clique.samples]) / (len(clique.samples) ** 2.0)
        self.updateAvailableIndices(clique, generalIdxtoAdd)

